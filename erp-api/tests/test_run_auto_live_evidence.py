import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from scripts import run_auto_live_evidence as live
from scripts.run_auto_live_evidence import missing_windows


def _run(start: date, end: date, *, fetched=1, persisted=1):
    return {
        "shop": "跨境12",
        "resource": "live",
        "window": (start, end),
        "status": "succeeded",
        "fetched": fetched,
        "persisted": persisted,
        "finished_at": datetime(2026, 10, 10, tzinfo=UTC),
    }


def test_missing_live_windows_reuses_historical_coverage() -> None:
    cutoff = date(2026, 10, 8)
    runs = [_run(date(2026, 8, 8), date(2026, 10, 7))]
    assert missing_windows("跨境12", cutoff, runs) == [
        (date(2026, 10, 7), date(2026, 10, 8))
    ]


def test_mismatched_fetched_count_does_not_cover_window() -> None:
    cutoff = date(2026, 10, 8)
    runs = [_run(date(2026, 8, 8), date(2026, 10, 8), fetched=2, persisted=1)]
    assert len(missing_windows("跨境12", cutoff, runs)) == 3


def test_live_planner_never_probes_before_sample_round(monkeypatch) -> None:
    tenant_id = uuid4()
    shops = [
        SimpleNamespace(tenant_id=tenant_id, shop_id=uuid4(), source_name=name)
        for name in live.BUSINESS_NAMES
    ]
    checked = []

    class Health:
        def __init__(self, _redis):
            pass

        async def get(self, _tenant_id, _shop_id):
            return SimpleNamespace(state="online", session_available=True)

    async def sample_ready(_database, _tenant_id, shop_id, *, now):
        checked.append(shop_id)
        return False

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Official live API was reached before sample completion")

    monkeypatch.setattr(live, "get_settings", lambda: SimpleNamespace(affiliate_export_tenant_id=tenant_id))
    monkeypatch.setattr(live, "_active_live_shops", lambda _database: asyncio.sleep(0, result=shops))
    monkeypatch.setattr(live, "AffiliateCaptureHealthRepository", Health)
    monkeypatch.setattr(live, "sample_round_releases_affiliate", sample_ready)
    monkeypatch.setattr(live, "latest_recent_live_observation", forbidden)
    plan, reason = asyncio.run(
        live.plan_next(object(), object(), datetime(2026, 10, 9, 16, 10, tzinfo=UTC))
    )
    assert plan is None and reason == "no_due_live_work"
    assert len(checked) == 5
