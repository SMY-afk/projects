from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentAdapterRegistry,
    PlatformFulfillmentCommand,
    PlatformFulfillmentError,
    PlatformFulfillmentResult,
)
from erp_api.services.platform_fulfillment_outbox_repository import ClaimedFulfillment
from erp_api.services.platform_fulfillment_service import PlatformFulfillmentService
from erp_api.services.tiktok_transport import TikTokApiError


class FakeRepository:
    def __init__(self, command) -> None:
        self.command = command
        self.failures = []
        self.succeeded = []

    async def claim(self, tenant_id, event_id, **kwargs):
        return ClaimedFulfillment(event_id, 1)

    async def load_command(self, tenant_id, event_id):
        return self.command

    async def succeed(self, tenant_id, event_id, request_id):
        self.succeeded.append((event_id, request_id))

    async def fail(self, tenant_id, event_id, **kwargs):
        self.failures.append(kwargs)


class FakeAdapter:
    platform = "tiktok"

    def __init__(self, error=None) -> None:
        self.error = error

    async def fulfill(self, command):
        if self.error:
            raise self.error
        return PlatformFulfillmentResult("request-1")


def test_adapter_registry_normalizes_platform_and_rejects_duplicates() -> None:
    adapter = FakeAdapter()
    registry = PlatformFulfillmentAdapterRegistry([adapter])

    assert registry.get(" TikTok ") is adapter
    with pytest.raises(ValueError, match="Duplicate"):
        PlatformFulfillmentAdapterRegistry([adapter, FakeAdapter()])


def _command():
    event_id, tenant_id = uuid4(), uuid4()
    return PlatformFulfillmentCommand(
        event_id=event_id,
        tenant_id=tenant_id,
        shop_id=uuid4(),
        platform="tiktok",
        platform_order_id="order-1",
        platform_package_id="package-1",
        tracking_number="TRACK-1",
        platform_carrier_id="provider-1",
        shipped_at=datetime.now(UTC),
        idempotency_key="shipment:1",
    )


@pytest.mark.asyncio
async def test_service_marks_success_after_adapter_callback() -> None:
    command = _command()
    repository = FakeRepository(command)
    service = PlatformFulfillmentService(
        repository,
        PlatformFulfillmentAdapterRegistry([FakeAdapter()]),
        max_tries=5,
        retry_base_seconds=30,
        processing_timeout=timedelta(minutes=10),
    )

    result = await service.process(command.tenant_id, command.event_id)

    assert result.status == "succeeded"
    assert repository.succeeded == [(command.event_id, "request-1")]


@pytest.mark.asyncio
async def test_service_persists_retry_without_exposing_upstream_message() -> None:
    command = _command()
    repository = FakeRepository(command)
    adapter = FakeAdapter(
        PlatformFulfillmentError(
            "sensitive upstream response", code="temporary_failure", retryable=True
        )
    )
    service = PlatformFulfillmentService(
        repository,
        PlatformFulfillmentAdapterRegistry([adapter]),
        max_tries=5,
        retry_base_seconds=30,
        processing_timeout=timedelta(minutes=10),
    )

    result = await service.process(command.tenant_id, command.event_id)

    assert result.status == "retry_wait"
    assert result.retry_after_seconds == 30
    assert repository.failures[0]["code"] == "temporary_failure"
    assert "sensitive" not in repository.failures[0]["summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform_code", "expected_status"),
    [("36009003", "retry_wait"), ("21011022", "failed")],
)
async def test_service_retries_only_retryable_tiktok_business_errors(
    platform_code, expected_status
) -> None:
    command = _command()
    repository = FakeRepository(command)
    error = TikTokApiError(
        "sensitive upstream response",
        code=platform_code,
        status_code=502,
        upstream_status_code=200,
    )
    service = PlatformFulfillmentService(
        repository,
        PlatformFulfillmentAdapterRegistry([FakeAdapter(error)]),
        max_tries=5,
        retry_base_seconds=30,
        processing_timeout=timedelta(minutes=10),
    )

    result = await service.process(command.tenant_id, command.event_id)

    assert result.status == expected_status
    assert repository.failures[0]["code"] == f"tiktok_api_{platform_code}"
