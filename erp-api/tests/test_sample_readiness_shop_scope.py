"""Sample writes require this shop's fresh source and a verified daily batch."""

from datetime import date

import pytest

from erp_api.services import sample_business_readiness as module
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("target_ready,daily_ready,receipt_ready", [
    (True, True, True), (False, True, True), (True, False, True), (True, True, False),
])
async def test_other_shop_outage_does_not_block_fresh_target(monkeypatch, target_ready, daily_ready, receipt_ready):
    thresholds = []
    report = {
        "sample_all_ok": False,
        "daily_local_all_ready": daily_ready,
        "shops": [{
            "shop": label,
            "sample_ok": target_ready if label == "cross-border-3" else False,
            "available_dates": {resource: "2026-10-08" for resource in ("creators", "videos", "liveAccounts")},
        } for label in SHOPS],
    }

    async def build_report(sample_stale_seconds):
        thresholds.append(sample_stale_seconds)
        return report

    async def noop(*_):
        return None

    async def receipt(batch_date):
        assert batch_date == date(2026, 10, 9)
        return receipt_ready

    checker = module.SampleBusinessReadiness()
    monkeypatch.setattr(checker, "_require_readyz", noop)
    monkeypatch.setattr(checker, "_daily_sync_succeeded", receipt)
    monkeypatch.setattr(module, "build_report", build_report)
    monkeypatch.setattr(module, "_valid_creator_batch_date", lambda _: date(2026, 10, 9))
    if target_ready and receipt_ready:
        await checker.require_ready(tenant_id=TENANT_ID, shop_id=SHOPS["cross-border-3"])
    else:
        with pytest.raises(RuntimeError, match="sample_source_stale|valid_creator_sync_missing"):
            await checker.require_ready(tenant_id=TENANT_ID, shop_id=SHOPS["cross-border-3"])
    assert thresholds == [900]
