"""Sample readiness uses the isolated daily table clock and existing receipts."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from erp_api.services import sample_business_readiness as readiness
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("clock,required_batch,allowed", [
    ("2026-10-14T15:49:59+00:00", date(2026, 10, 13), True),
    ("2026-10-14T15:50:00+00:00", date(2026, 10, 13), True),
    ("2026-10-14T16:00:00+00:00", date(2026, 10, 13), True),
    ("2026-10-14T17:29:59+00:00", date(2026, 10, 13), True),
    ("2026-10-14T17:30:00+00:00", date(2026, 10, 14), False),
])
async def test_old_verified_table_remains_usable_until_0130(
    monkeypatch, clock, required_batch, allowed,
):
    now = datetime.fromisoformat(clock)
    checked = []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    async def readyz():
        checked.append("readyz")

    async def sample_report(seconds):
        assert seconds == 900
        checked.append("sample-freshness")
        return {"shops": [{"shop": label, "sample_ok": True} for label in SHOPS]}

    async def receipt(batch):
        checked.append(batch)
        assert batch == required_batch
        return batch == date(2026, 10, 13)

    checker = readiness.SampleBusinessReadiness()
    monkeypatch.setattr(readiness, "datetime", FrozenDateTime)
    monkeypatch.setattr(readiness, "build_report", sample_report)
    monkeypatch.setattr(checker, "_require_readyz", readyz)
    monkeypatch.setattr(checker, "_daily_sync_succeeded", receipt)
    if allowed:
        await checker.require_ready(tenant_id=TENANT_ID, shop_id=SHOPS["cross-border-3"])
    else:
        with pytest.raises(RuntimeError, match="valid_creator_sync_missing"):
            await checker.require_ready(tenant_id=TENANT_ID, shop_id=SHOPS["cross-border-3"])
    assert checked == ["readyz", "sample-freshness", required_batch]


@pytest.mark.asyncio
async def test_existing_success_receipt_pattern_is_unchanged(monkeypatch):
    checked = []

    class Redis:
        @classmethod
        def from_url(cls, url):
            assert url == "redis://test"
            return cls()

        async def scan_iter(self, *, match, count):
            checked.append((match, count))
            yield "valid-creator-sync:20261013:fingerprint:success"

        async def aclose(self):
            checked.append("closed")

    monkeypatch.setattr(readiness, "Redis", Redis)
    monkeypatch.setattr(readiness, "get_settings", lambda: SimpleNamespace(redis_url="redis://test"))
    assert await readiness.SampleBusinessReadiness._daily_sync_succeeded(date(2026, 10, 13))
    assert checked == [("valid-creator-sync:20261013:*:success", 20), "closed"]


def test_utc_and_beijing_clock_produce_the_same_readiness_batch():
    from zoneinfo import ZoneInfo

    now = datetime(2026, 10, 14, 17, 30, tzinfo=UTC)
    assert readiness._valid_creator_batch_date(now) == readiness._valid_creator_batch_date(
        now.astimezone(ZoneInfo("Asia/Shanghai"))) == date(2026, 10, 14)
