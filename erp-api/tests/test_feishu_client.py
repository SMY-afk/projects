import asyncio

import httpx
import pytest

from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_creator_export_service import build_feishu_creator_export
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import FeishuSampleTransport


@pytest.mark.asyncio
async def test_feishu_client_throttles_token_requests_and_retries(monkeypatch) -> None:
    admitted: list[int] = []
    attempted: list[int] = []

    class RecordingLimiter:
        async def acquire(self) -> None:
            admitted.append(len(admitted) + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        attempted.append(len(admitted))
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "token", "expire": 7200},
            )
        if len(attempted) == 2:
            return httpx.Response(429, json={"code": 99991400})
        return httpx.Response(200, json={"code": 0, "data": {"items": []}})

    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(
        "erp_api.services.feishu_client.shared_feishu_rate_limiter",
        lambda _redis_url: RecordingLimiter(),
    )
    feishu = FeishuClient(
        app_id="app",
        app_secret="secret",
        client=http_client,
        retry_delays=(0,),
    )

    assert await feishu.list_records("base", "table", params={"page_size": 1}) == {
        "items": []
    }
    assert attempted == [1, 2, 3]


@pytest.mark.asyncio
async def test_clients_share_cached_token_until_refresh_window(monkeypatch) -> None:
    now = [0.0]
    auth_calls = 0

    async def fake_request(self, method, path, *, retry_mode, **kwargs):
        nonlocal auth_calls
        assert method == "POST"
        assert path.endswith("/tenant_access_token/internal")
        auth_calls += 1
        return {
            "code": 0,
            "tenant_access_token": f"token-{auth_calls}",
            "expire": 100,
        }

    monkeypatch.setattr(FeishuSampleTransport, "request_json", fake_request)
    first = FeishuClient(
        app_id="shared-app",
        app_secret="shared-secret",
        clock=lambda: now[0],
        token_refresh_skew_seconds=10,
    )
    second = FeishuClient(
        app_id="shared-app",
        app_secret="shared-secret",
        clock=lambda: now[0],
        token_refresh_skew_seconds=10,
    )

    assert await asyncio.gather(
        first.tenant_access_token(), second.tenant_access_token()
    ) == ["token-1", "token-1"]
    now[0] = 89
    assert await second.tenant_access_token() == "token-1"
    now[0] = 91
    assert await first.tenant_access_token() == "token-2"
    assert auth_calls == 2


@pytest.mark.asyncio
async def test_injected_http_clients_keep_token_caches_isolated() -> None:
    auth_calls = 0

    def handler(request):
        nonlocal auth_calls
        auth_calls += 1
        return httpx.Response(
            200,
            json={
                "code": 0,
                "tenant_access_token": f"token-{auth_calls}",
                "expire": 7200,
            },
        )

    first_http = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    second_http = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    first = FeishuClient(app_id="app", app_secret="secret", client=first_http)
    second = FeishuClient(app_id="app", app_secret="secret", client=second_http)

    assert await first.tenant_access_token() == "token-1"
    assert await first.tenant_access_token() == "token-1"
    assert await second.tenant_access_token() == "token-2"
    assert auth_calls == 2


@pytest.mark.asyncio
async def test_token_without_valid_expiry_is_rejected() -> None:
    client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"code": 0, "tenant_access_token": "token"}
            )
        ),
    )
    feishu = FeishuClient(app_id="app", app_secret="secret", client=client)

    with pytest.raises(FeishuSampleError, match="invalid expiry"):
        await feishu.tenant_access_token()


@pytest.mark.asyncio
async def test_creator_export_reuses_token_across_export_calls(monkeypatch) -> None:
    auth_calls = 0
    record_calls = 0

    async def fake_request(self, method, path, *, retry_mode, **kwargs):
        nonlocal auth_calls, record_calls
        if path.endswith("/tenant_access_token/internal"):
            auth_calls += 1
            return {"code": 0, "tenant_access_token": "cached-token", "expire": 7200}
        record_calls += 1
        assert kwargs["headers"]["Authorization"] == "Bearer cached-token"
        return {"code": 0, "data": {"total": 0, "items": [], "has_more": False}}

    monkeypatch.setattr(FeishuSampleTransport, "request_json", fake_request)
    await build_feishu_creator_export("shared-export-app", "shared-export-secret")
    await build_feishu_creator_export("shared-export-app", "shared-export-secret")

    assert auth_calls == 1
    assert record_calls == 2


@pytest.mark.asyncio
async def test_refresh_failure_reuses_still_valid_token_until_expiry() -> None:
    now = [0.0]
    auth_calls = 0

    def handler(request):
        nonlocal auth_calls
        auth_calls += 1
        if auth_calls > 1:
            raise httpx.ConnectError("auth unavailable", request=request)
        return httpx.Response(
            200, json={"code": 0, "tenant_access_token": "valid-token", "expire": 100}
        )

    http_client = httpx.AsyncClient(
        base_url="https://example.invalid/configure-resource", transport=httpx.MockTransport(handler)
    )
    feishu = FeishuClient(
        app_id="app",
        app_secret="secret",
        client=http_client,
        clock=lambda: now[0],
        token_refresh_skew_seconds=10,
        retry_delays=(),
    )

    assert await feishu.tenant_access_token() == "valid-token"
    now[0] = 91
    assert await feishu.tenant_access_token() == "valid-token"
    now[0] = 95
    assert await feishu.tenant_access_token() == "valid-token"
    assert auth_calls == 2
    now[0] = 101
    with pytest.raises(FeishuSampleError):
        await feishu.tenant_access_token()
