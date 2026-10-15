from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from dateutil.relativedelta import relativedelta
from pydantic import SecretStr

from scripts import daily_valid_creator_io as io
from scripts import daily_valid_creator_writer as writer
from scripts.daily_valid_creator_dates import parse_shop_cutoffs


def test_daily_valid_creator_write_target_is_sample_copy():
    assert io.BASE == "exampleb6b20e30bcdc75e12b5f"
    assert io.TABLE == "tblexamplef1d0cfa5"
    assert writer.BASE == io.BASE
    assert writer.TABLE == io.TABLE


def test_daily_sync_uses_dedicated_feishu_credentials(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        io,
        "get_settings",
        lambda: SimpleNamespace(
            feishu_app_id="old-id",
            feishu_app_secret=SecretStr("old-secret"),
            feishu_new_app_id="new-id",
            feishu_new_app_secret=SecretStr("new-secret"),
        ),
    )
    monkeypatch.setattr(io, "FeishuClient", fake_client)
    io.feishu_client()
    assert captured == {
        "app_id": "new-id",
        "app_secret": "new-secret",
        "business_type": "daily_valid_creator_sync",
    }


@pytest.mark.asyncio
async def test_fetch_sources_allows_slow_complete_prerequisite_export(monkeypatch):
    captured = {}

    class StopAfterClientConstruction(Exception):
        pass

    def fake_client(**kwargs):
        captured.update(kwargs)
        raise StopAfterClientConstruction

    monkeypatch.setattr(io.httpx, "AsyncClient", fake_client)
    monkeypatch.setattr(
        io,
        "get_settings",
        lambda: SimpleNamespace(
            affiliate_export_service_token=SecretStr("test-token")
        ),
    )
    with pytest.raises(StopAfterClientConstruction):
        await io.fetch_sources({})

    timeout = captured["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10
    assert timeout.read == 480
    assert timeout.write == 30
    assert timeout.pool == 30


@pytest.mark.asyncio
async def test_target_identity_rejects_original_sample_base():
    class Client:
        async def tenant_access_token(self):
            return "test-token"

        async def request_json(self, method, path, **kwargs):
            assert method == "GET"
            assert io.BASE in path
            return {"data": {"app": {"name": "样品"}}}

    with pytest.raises(ValueError, match="Target Base title mismatch"):
        await io.verify_target_identity(Client())


@pytest.mark.asyncio
async def test_fetch_sources_requests_each_shops_own_window(monkeypatch):
    monkeypatch.setattr(io, "feishu_client", lambda: object())
    monkeypatch.setattr(io, "read_creator_tables", AsyncMock(return_value=[]))
    cutoffs = parse_shop_cutoffs(
        [
            "跨境3,2026-10-03,2026-10-02,2026-10-04",
            "跨境7,2026-10-02,2026-10-01,2026-10-01",
            "跨境4,2026-10-03,2026-10-02,2026-10-02",
            "跨境12,2026-10-01,2026-09-30,2026-10-01",
            "本土店,2026-10-03,2026-10-01,2026-10-02",
        ],
        today=date(2026, 10, 5),
    )
    requested = []

    def respond(request):
        assert request.headers.get("x-erp-service-token") == "test-token"
        if request.url.path.endswith("/feishu-export"):
            return httpx.Response(200, json={"source": "feishu-bitable-readonly"})
        name = request.url.params["shop"]
        start, end = request.url.params["from"], request.url.params["to"]
        requested.append((name, start, end))
        return httpx.Response(
            200,
            json={
                "source": "local-erp-affiliate-center",
                "window": {"from": start, "to": end},
                "shops": [{"shopName": name}],
            },
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        io.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    monkeypatch.delenv("AFFILIATE_EXPORT_SERVICE_TOKEN", raising=False)
    monkeypatch.setattr(
        io,
        "get_settings",
        lambda: SimpleNamespace(affiliate_export_service_token=SecretStr("test-token")),
    )
    feishu, high, low = await io.fetch_sources(cutoffs)
    assert feishu["source"] == "feishu-bitable-readonly"
    assert [item["shopName"] for item in high["shops"]] == list(cutoffs)
    assert [item["shopName"] for item in low["shops"]] == list(cutoffs)
    expected = [
        (name, str(end - relativedelta(months=2)), str(end))
        for resource in ("creators", "videos")
        for name, dates in cutoffs.items()
        for end in (
            max(dates["creators"], dates["liveAccounts"])
            if resource == "creators"
            else dates[resource],
        )
    ]
    assert sorted(requested) == sorted(expected)


@pytest.mark.asyncio
async def test_fetch_sources_rejects_old_five_shop_export(monkeypatch):
    monkeypatch.setattr(io, "feishu_client", lambda: object())
    monkeypatch.setattr(io, "read_creator_tables", AsyncMock(return_value=[]))
    cutoffs = parse_shop_cutoffs(
        [
            f"{name},2026-10-03,2026-10-01,2026-10-02"
            for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
        ],
        today=date(2026, 10, 5),
    )

    def respond(request):
        if request.url.path.endswith("/feishu-export"):
            return httpx.Response(200, json={"source": "feishu-bitable-readonly"})
        return httpx.Response(
            200,
            json={
                "source": "local-erp-affiliate-center",
                "window": {
                    "from": request.url.params["from"],
                    "to": request.url.params["to"],
                },
                "shops": [{"shopName": name} for name in cutoffs],
            },
        )

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        io.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(respond), **kwargs
        ),
    )
    monkeypatch.setattr(
        io,
        "get_settings",
        lambda: SimpleNamespace(affiliate_export_service_token=SecretStr("test-token")),
    )
    with pytest.raises(ValueError, match="ERP export identity mismatch"):
        await io.fetch_sources(cutoffs)
