import httpx
import pytest

from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import FeishuSampleTransport


def _transport(handler, delays):
    async def sleep(seconds):
        delays.append(seconds)

    return FeishuSampleTransport(
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource",
            transport=httpx.MockTransport(handler),
        ),
        sleeper=sleep,
    )


@pytest.mark.asyncio
async def test_rate_limit_uses_bounded_exponential_backoff() -> None:
    calls = 0
    delays = []

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls < 5:
            return httpx.Response(429, json={"code": 99991400})
        return httpx.Response(200, json={"code": 0, "data": {}})

    result = await _transport(handler, delays).request_json(
        "GET", "/open-apis/bitable/v1/apps/a/tables/t/records", retry_mode="idempotent"
    )

    assert result["code"] == 0
    assert calls == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_timeout_stops_after_four_retries() -> None:
    calls = 0
    delays = []

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(FeishuSampleError) as error:
        await _transport(handler, delays).request_json(
            "GET",
            "/open-apis/bitable/v1/apps/a/tables/t/records",
            retry_mode="idempotent",
        )

    assert error.value.error_code == "timeout"
    assert calls == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]


@pytest.mark.asyncio
async def test_network_error_retries_idempotent_request_only() -> None:
    calls = 0
    delays = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"code": 0})

    await _transport(handler, delays).request_json(
        "PUT",
        "/open-apis/bitable/v1/apps/a/tables/t/records/r",
        retry_mode="idempotent",
    )

    assert calls == 3
    assert delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_ambiguous_create_timeout_is_not_resent() -> None:
    calls = 0
    delays = []

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("unknown result", request=request)

    with pytest.raises(FeishuSampleError) as error:
        await _transport(handler, delays).request_json(
            "POST",
            "/open-apis/bitable/v1/apps/a/tables/t/records/batch_create",
            retry_mode="rate_limit",
        )

    assert error.value.error_code == "timeout"
    assert calls == 1
    assert delays == []


@pytest.mark.asyncio
async def test_explicit_rate_limit_can_retry_create() -> None:
    calls = 0
    delays = []

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"code": 99991400})
        return httpx.Response(200, json={"code": 0})

    await _transport(handler, delays).request_json(
        "POST",
        "/open-apis/bitable/v1/apps/a/tables/t/records/batch_create",
        retry_mode="rate_limit",
    )

    assert calls == 2
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_http_request_timeout_retries_but_business_rejection_does_not() -> None:
    calls = 0
    delays = []

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(408)
        return httpx.Response(403, json={"code": 99991668})

    with pytest.raises(FeishuSampleError) as error:
        await _transport(handler, delays).request_json(
            "GET",
            "/open-apis/bitable/v1/apps/a/tables/t/records",
            retry_mode="idempotent",
        )

    assert error.value.error_code == "99991668"
    assert calls == 2
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_sample_client_create_retries_explicit_429_only() -> None:
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"code": 99991400})
        return httpx.Response(200, json={"code": 0, "data": {}})

    class NoopLimiter:
        async def acquire(self):
            return None

    client = FeishuSampleClient(
        app_id="app",
        app_secret="secret",
        base_token="base",
        table_id="table",
        client=httpx.AsyncClient(
            base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
        ),
        retry_delays=(0,),
    )
    client._feishu._rate_limiter = NoopLimiter()

    assert (
        await client._request(
            "POST",
            "/open-apis/bitable/v1/apps/base/tables/table/records",
            token="token",
        )
        == {}
    )
    assert calls == 2


def test_retry_configuration_has_hard_limit() -> None:
    with pytest.raises(ValueError, match="four retries"):
        FeishuSampleTransport(retry_delays=(1, 2, 4, 8, 16))
