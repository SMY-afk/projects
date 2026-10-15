from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import run_ziniao_affiliate_watch as watch


class FakeHealthRepository:
    def __init__(self) -> None:
        self.states: list[str] = []

    async def record(self, _tenant_id, _shop_id, state: str) -> None:
        self.states.append(state)


@pytest.mark.asyncio
async def test_idle_health_reports_online_when_ziniao_browser_is_available(
    monkeypatch,
) -> None:
    async def ensure_browser(_settings):
        return SimpleNamespace(debugging_port=9222)

    monkeypatch.setattr(watch, "_ensure_browser", ensure_browser)
    health = FakeHealthRepository()
    shop = SimpleNamespace(tenant_id=uuid4(), id=uuid4())

    await watch._record_idle_health(object(), shop, health)

    assert health.states == ["online"]


@pytest.mark.asyncio
async def test_idle_health_reports_offline_when_ziniao_browser_is_unavailable(
    monkeypatch,
) -> None:
    async def ensure_browser(_settings):
        raise RuntimeError("offline")

    monkeypatch.setattr(watch, "_ensure_browser", ensure_browser)
    health = FakeHealthRepository()
    shop = SimpleNamespace(tenant_id=uuid4(), id=uuid4())

    await watch._record_idle_health(object(), shop, health)

    assert health.states == ["browser_offline"]
