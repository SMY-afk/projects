import httpx
import pytest

from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError


def _client(handler, *, retry_delays: tuple[float, ...]) -> FeishuSampleBatchClient:
    return FeishuSampleBatchClient(
        app_id="app-id",
        app_secret="app-secret",
        base_token="base-token",
        table_id="table-id",
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource",
            transport=httpx.MockTransport(handler),
        ),
        retry_delays=retry_delays,
    )


def _token_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "code": 0,
            "tenant_access_token": "tenant-token",
            "expire": 7200,
        },
    )


@pytest.mark.asyncio
async def test_batch_update_retries_rate_limit_and_captures_request_ids() -> None:
    batch_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                headers={"x-tt-logid": "token-log"},
                json={
                    "code": 0,
                    "tenant_access_token": "tenant-token",
                    "expire": 7200,
                },
            )
        batch_calls += 1
        if batch_calls == 1:
            return httpx.Response(
                429,
                headers={"x-tt-logid": "rate-limit-log"},
                json={"code": 99991400, "msg": "rate limited"},
            )
        return httpx.Response(
            200,
            headers={"x-tt-logid": "success-log"},
            json={
                "code": 0,
                "data": {"records": [{"record_id": "rec-1"}]},
            },
        )

    client = _client(handler, retry_delays=(0,))
    with client.capture_evidence() as trace:
        updated = await client.batch_update_records(
            [("rec-1", {"同步键（系统）": "shop:sample-1"})]
        )

    assert updated == ("rec-1",)
    assert batch_calls == 2
    assert trace.request_ids == ["token-log", "rate-limit-log", "success-log"]
    assert [item.error_code for item in trace.responses] == [None, "99991400", None]


@pytest.mark.asyncio
async def test_batch_update_retries_data_not_ready() -> None:
    batch_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        batch_calls += 1
        if batch_calls == 1:
            return httpx.Response(
                400,
                headers={"x-tt-logid": "data-not-ready-log"},
                json={"code": 1254607, "msg": "data not ready"},
            )
        return httpx.Response(
            200,
            headers={"x-tt-logid": "success-log"},
            json={
                "code": 0,
                "data": {"records": [{"record_id": "rec-1"}]},
            },
        )

    client = _client(handler, retry_delays=(0,))
    with client.capture_evidence() as trace:
        updated = await client.batch_update_records([("rec-1", {"PPS": "4.4/5.0"})])

    assert updated == ("rec-1",)
    assert batch_calls == 2
    assert [item.error_code for item in trace.responses] == [None, "1254607", None]


@pytest.mark.asyncio
async def test_batch_create_does_not_retry_ambiguous_server_failure() -> None:
    batch_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        batch_calls += 1
        return httpx.Response(
            503,
            headers={"x-tt-logid": "server-log"},
            json={"code": 1254607, "msg": "server failure"},
        )

    client = _client(handler, retry_delays=(0, 0))
    with (
        client.capture_evidence() as trace,
        pytest.raises(FeishuSampleError) as exc_info,
    ):
        await client.batch_create_records([{"同步键（系统）": "shop:sample-1"}])

    assert batch_calls == 1
    assert exc_info.value.error_code == "1254607"
    assert exc_info.value.request_id == "server-log"
    assert trace.request_ids == ["server-log"]


@pytest.mark.asyncio
async def test_batch_create_retries_explicit_rate_limit_only() -> None:
    batch_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        batch_calls += 1
        if batch_calls == 1:
            return httpx.Response(
                400,
                json={
                    "code": 99991400,
                    "msg": "rate limited",
                    "error": {"log_id": "body-rate-limit-log"},
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "records": [
                        {
                            "record_id": "rec-1",
                            "fields": {"同步键（系统）": "shop:sample-1"},
                        }
                    ]
                },
            },
        )

    client = _client(handler, retry_delays=(0,))
    with client.capture_evidence() as trace:
        created = await client.batch_create_records(
            [{"同步键（系统）": "shop:sample-1"}]
        )

    assert created == {"shop:sample-1": "rec-1"}
    assert batch_calls == 2
    assert trace.request_ids == ["body-rate-limit-log"]


@pytest.mark.asyncio
async def test_batch_update_stops_after_configured_retry_limit() -> None:
    batch_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_calls
        if request.url.path.endswith("/tenant_access_token/internal"):
            return _token_response()
        batch_calls += 1
        return httpx.Response(
            429,
            headers={"x-tt-logid": f"rate-limit-{batch_calls}"},
            json={"code": 99991400, "msg": "rate limited"},
        )

    client = _client(handler, retry_delays=(0,))
    with (
        client.capture_evidence() as trace,
        pytest.raises(FeishuSampleError) as exc_info,
    ):
        await client.batch_update_records(
            [("rec-1", {"同步键（系统）": "shop:sample-1"})]
        )

    assert batch_calls == 2
    assert exc_info.value.error_code == "99991400"
    assert trace.request_ids == ["rate-limit-1", "rate-limit-2"]
