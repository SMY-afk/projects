import json
import logging

import httpx
import pytest

from erp_api.core.logging import JsonFormatter
from erp_api.services.feishu_api_logging import log_api_call, request_started
from erp_api.services.feishu_creator_export_service import (
    FeishuCreatorExportError,
    build_feishu_creator_export,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import FeishuSampleTransport


@pytest.fixture(autouse=True)
def capture_feishu_api_logs(caplog):
    logger = logging.getLogger("erp_api.feishu_api")
    original_propagate = logger.propagate
    logger.propagate = False
    logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        logger.removeHandler(caplog.handler)
        logger.propagate = original_propagate


def _events(caplog):
    return [
        json.loads(JsonFormatter().format(record))
        for record in caplog.records
        if record.name == "erp_api.feishu_api"
    ]


@pytest.mark.parametrize(
    ("path", "api_name"),
    [
        ("/open-apis/im/v1/messages/secret-message", "DELETE im.messages.item"),
        (
            "/open-apis/sheets/v2/spreadsheets/secret-sheet/values/secret-range",
            "DELETE sheets.values",
        ),
        (
            "/open-apis/bitable/v1/apps/secret-base/tables/secret-table/records/batch_update",
            "DELETE bitable.records.batch_update",
        ),
    ],
)
def test_api_name_omits_remote_identifiers(caplog, path, api_name) -> None:
    request_time, started_at = request_started()
    with caplog.at_level(logging.INFO, logger="erp_api.feishu_api"):
        log_api_call(
            "DELETE",
            path,
            business_type="notification",
            request_time=request_time,
            started_at=started_at,
            status_code=200,
            success=True,
        )

    event = _events(caplog)[0]
    assert event["api_name"] == api_name
    assert "secret" not in json.dumps(event)


@pytest.mark.asyncio
async def test_transport_logs_each_attempt_and_business_failure(caplog) -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"code": 99991400})
        return httpx.Response(200, json={"code": 0, "data": {}})

    client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    transport = FeishuSampleTransport(client=client, retry_delays=(0,))
    with caplog.at_level(logging.INFO, logger="erp_api.feishu_api"):
        await transport.request_json(
            "GET",
            "/open-apis/bitable/v1/apps/secret-base/tables/secret-table/records",
            retry_mode="idempotent",
            params={"page_token": "secret-page"},
        )

    events = _events(caplog)
    assert len(events) == 2
    assert [item["status_code"] for item in events] == [429, 200]
    assert [item["success"] for item in events] == [False, True]
    assert all(item["api_name"] == "GET bitable.records.list" for item in events)
    assert all(item["business_type"] == "sample_management" for item in events)
    assert all(item["request_time"] and item["duration_ms"] >= 0 for item in events)
    assert "secret" not in json.dumps(events)


@pytest.mark.asyncio
async def test_transport_logs_http_200_feishu_error(caplog) -> None:
    def business_failure(request):
        return httpx.Response(200, json={"code": 99991403})

    client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource",
        transport=httpx.MockTransport(business_failure),
    )
    transport = FeishuSampleTransport(client=client, retry_delays=())
    with (
        caplog.at_level(logging.INFO, logger="erp_api.feishu_api"),
        pytest.raises(FeishuSampleError),
    ):
        await transport.request_json(
            "GET", "/open-apis/bitable/v1/apps/a/tables/t/records", retry_mode="none"
        )

    assert _events(caplog)[0]["status_code"] == 200
    assert _events(caplog)[0]["success"] is False


@pytest.mark.asyncio
async def test_transport_logs_missing_http_response_with_null_status(caplog) -> None:
    def handler(request):
        raise httpx.ConnectError("secret transport detail", request=request)

    client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    transport = FeishuSampleTransport(client=client, retry_delays=())
    with (
        caplog.at_level(logging.INFO, logger="erp_api.feishu_api"),
        pytest.raises(FeishuSampleError),
    ):
        await transport.request_json(
            "GET", "/open-apis/bitable/v1/apps/a/tables/t/records", retry_mode="none"
        )

    assert _events(caplog)[0]["status_code"] is None
    assert _events(caplog)[0]["success"] is False
    assert "secret transport detail" not in json.dumps(_events(caplog))


@pytest.mark.asyncio
async def test_creator_export_uses_same_api_log(caplog) -> None:
    def handler(request):
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "secret", "expire": 7200},
            )
        return httpx.Response(403, json={"code": 99991403})

    with (
        caplog.at_level(logging.INFO, logger="erp_api.feishu_api"),
        pytest.raises(FeishuCreatorExportError),
    ):
        await build_feishu_creator_export(
            "app",
            "secret",
            http_transport=httpx.MockTransport(handler),
            retry_delays=(),
        )

    events = _events(caplog)
    assert len(events) == 2
    assert events[0]["business_type"] == "authentication"
    assert all(item["business_type"] == "creator_export" for item in events[1:])
    assert all(item["success"] is False for item in events[1:])
