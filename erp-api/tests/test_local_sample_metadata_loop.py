from datetime import UTC, datetime

import pytest

from scripts.local_capture_guard import CaptureGuardError
from scripts.local_sample_metadata_rules import LOCAL_SHOP, LOCAL_TENANT
from scripts.run_local_sample_metadata_bridge import cycle


@pytest.mark.asyncio
async def test_no_candidates_means_zero_browser_calls(tmp_path):
    seen = []

    def send(operation, _payload):
        seen.append(operation)
        return {"status": "candidates", "manifest": {
            "tenant_id": LOCAL_TENANT, "shop_id": LOCAL_SHOP,
            "checked_at": datetime.now(UTC).isoformat(), "rows": [],
        }}

    async def capture(*_args, **_options):
        raise AssertionError("No UI is permitted without candidates")

    assert (await cycle(tmp_path, send=send, take_capture=capture))["status"] == "idle"
    assert seen == ["probe"]


@pytest.mark.asyncio
async def test_pending_capture_is_delivered_before_probe_or_new_capture(tmp_path):
    from scripts.local_sample_metadata_state import MetadataCaptureState

    state = MetadataCaptureState(tmp_path / "pending")
    row = state.stage({}, {"observed_at": datetime.now(UTC).isoformat()})
    state.mark_submitting(row["attempt_id"])
    seen = []

    def send(operation, _payload):
        seen.append(operation)
        return {"status": "deferred", "reason": "sample_shop_busy"}

    result = await cycle(tmp_path, send=send)
    assert result["status"] == "deferred"
    assert seen == ["status"]


@pytest.mark.asyncio
async def test_foreign_or_stale_probe_never_calls_browser(tmp_path):
    def send(*_args):
        return {"status": "candidates", "manifest": {
            "tenant_id": LOCAL_TENANT, "shop_id": "other",
            "checked_at": datetime.now(UTC).isoformat(), "rows": [{"id": "one"}],
        }}

    async def capture(*_args, **_options):
        raise AssertionError("Foreign probe must not touch UI")

    with pytest.raises(RuntimeError, match="probe_scope"):
        await cycle(tmp_path, send=send, take_capture=capture)


@pytest.mark.asyncio
async def test_security_pause_blocks_pending_delivery_without_clearing_it(tmp_path, monkeypatch):
    from scripts.local_sample_metadata_state import MetadataCaptureState

    state = MetadataCaptureState(tmp_path / "pending")
    state.stage({}, {"observed_at": datetime.now(UTC).isoformat()})
    monkeypatch.setattr("scripts.run_local_sample_metadata_bridge.pause_reason", lambda *_: "captcha")

    def send(*_args):
        raise AssertionError("Security pause must stop metadata apply")

    assert (await cycle(tmp_path, send=send))["status"] == "paused"
    assert state.load_pending()["phase"] == "captured"


@pytest.mark.asyncio
async def test_candidates_require_real_official_priority_before_any_ui(tmp_path):
    manifest = {"tenant_id": LOCAL_TENANT, "shop_id": LOCAL_SHOP,
                "checked_at": datetime.now(UTC).isoformat(),
                "rows": [{"id": "one", "platform_application_id": "one", "creator_username": "alice"}]}

    def send(*_args):
        return {"status": "candidates", "manifest": manifest}

    def refresh():
        raise CaptureGuardError("official_free_probe_failed")

    async def capture(*_args):
        raise AssertionError("Never navigate when official source priority is unknown")

    with pytest.raises(CaptureGuardError, match="official_free_probe_failed"):
        await cycle(tmp_path, send=send, take_capture=capture, refresh_priority=refresh)


@pytest.mark.asyncio
async def test_restart_after_receipt_before_raw_ack_finishes_ack_first(tmp_path, monkeypatch):
    from scripts.local_sample_metadata_state import MetadataCaptureState

    state = MetadataCaptureState(tmp_path / "pending")
    row = state.stage({}, {"observed_at": datetime.now(UTC).isoformat()}, "our-raw")
    state.mark_completed(row["attempt_id"], {"status": "completed", "attempt_id": row["attempt_id"]})
    seen = []
    monkeypatch.setattr("scripts.run_local_sample_metadata_bridge.finish_raw", lambda *_args, **_kw: seen.append("ack"))

    def send(*_args):
        seen.append("probe")
        return {"status": "candidates", "manifest": {
            "tenant_id": LOCAL_TENANT, "shop_id": LOCAL_SHOP,
            "checked_at": datetime.now(UTC).isoformat(), "rows": [],
        }}

    await cycle(tmp_path, send=send)
    assert seen == ["ack", "probe"]
