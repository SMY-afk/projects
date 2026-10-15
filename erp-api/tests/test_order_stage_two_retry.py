"""Transient order reads and failed runs must retry without replaying writes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from arq import Retry

from erp_api.services.tiktok_order_client import HttpTikTokOrderClient
from erp_api.services.tiktok_transport import TikTokRateLimitError, TikTokTransport
from erp_api.workers.order_jobs import process_order_webhook_job, sync_order_job


@pytest.mark.parametrize("failure", [429, 503, "timeout", "network"])
def test_order_search_read_retries_transient_failure(failure):
    attempts = []
    delays = []

    async def sleep(delay):
        delays.append(delay)

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("test-only", request=request)
            if failure == "network":
                raise httpx.ConnectError("test-only", request=request)
            return httpx.Response(failure, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"data": {"orders": [], "next_page_token": ""}})

    client = HttpTikTokOrderClient(TikTokTransport(
        base_url="https://mock.invalid", app_key="test-only", app_secret="test-only",
        http_transport=httpx.MockTransport(handler), sleep=sleep))
    result = asyncio.run(client.list_orders("test-only", shop_cipher="test-only"))
    assert result.orders == []
    assert len(attempts) == 2
    assert len(delays) == 1
    if isinstance(failure, int):
        assert delays == [2]


@pytest.mark.parametrize("summary", [
    "TikTokRateLimitError code=rate_limited status=429: rate limited",
    "TikTokTimeoutError: request timed out",
    "TikTokClientError: request failed",
    "TikTokApiError code=http_503 status=502: rejected",
])
def test_failed_transient_order_run_is_requeued(summary):
    service = SimpleNamespace(sync_orders=AsyncMock(return_value=SimpleNamespace(
        status="failed", error=summary)))
    with pytest.raises(Retry):
        asyncio.run(sync_order_job({"order_sync_service": service, "job_try": 1},
                                  str(uuid4()), str(uuid4())))
    assert service.sync_orders.await_count == 1


def test_permanent_permission_failure_is_not_retried():
    result = SimpleNamespace(status="failed", error="TikTokApiError code=http_403 status=502: rejected")
    service = SimpleNamespace(sync_orders=AsyncMock(return_value=result))
    assert asyncio.run(sync_order_job({"order_sync_service": service},
                                     str(uuid4()), str(uuid4()))) is result


def test_successful_run_is_not_retried():
    result = SimpleNamespace(status="succeeded", error=None)
    service = SimpleNamespace(sync_orders=AsyncMock(return_value=result))
    assert asyncio.run(sync_order_job({"order_sync_service": service},
                                     str(uuid4()), str(uuid4()))) is result


def test_refresh_rate_limit_before_run_creation_retries():
    service = SimpleNamespace(sync_orders=AsyncMock(side_effect=TikTokRateLimitError(
        retry_after_seconds=60)))
    with pytest.raises(Retry):
        asyncio.run(sync_order_job({"order_sync_service": service}, str(uuid4()), str(uuid4())))


def test_webhook_retry_is_not_marked_succeeded():
    webhook = SimpleNamespace(get_event=AsyncMock(return_value=SimpleNamespace(shop_id=uuid4())),
                              finish_event=AsyncMock())
    service = SimpleNamespace(sync_orders=AsyncMock(return_value=SimpleNamespace(
        status="failed", error="TikTokTimeoutError: request timed out")))
    with pytest.raises(Retry):
        asyncio.run(process_order_webhook_job({"webhook_service": webhook,
                    "order_sync_service": service}, str(uuid4()), str(uuid4())))
    assert webhook.finish_event.await_args.kwargs["status"] == "failed"
