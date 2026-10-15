"""The local scheduler must prefer samples and exact shop identity."""

import asyncio
import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.run_auto_affiliate_exports import (
    choose_window,
    export_args,
    load_interruption_cooldown,
    process_lock,
    run,
)


def _plan():
    return {
        "window_open": True,
        "shops": [{
            "business_name": "跨境4",
            "shop_id": "50770999-40ce-5b84-bb01-13701932bdf1",
            "timezone": "America/Los_Angeles", "currency": "USD",
            "health_ready": True, "sample_released": True,
            "cutoffs": {"creators": {
                "date": "2026-10-08", "observed_at": datetime.now(UTC).isoformat(),
            }},
            "missing": [{
                "resource": "creators", "start": "2026-10-07", "end": "2026-10-08",
            }],
        }],
    }


def test_sample_round_is_required(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.run_auto_affiliate_exports.sample_idle_status",
        lambda *_args, **_kwargs: "stored",
    )
    args = Namespace(shop_label=None, sample_status_dir=tmp_path)
    plan = _plan()
    plan["shops"][0]["sample_released"] = False
    assert choose_window(plan, args) is None


def test_sample_idle_and_fresh_source_select_only_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.run_auto_affiliate_exports.sample_idle_status",
        lambda *_args, **_kwargs: "stored",
    )
    args = Namespace(shop_label=None, sample_status_dir=tmp_path)
    shop, window, label = choose_window(_plan(), args)
    assert (label, window["resource"], window["start"], window["end"]) == (
        "cross-border-4", "creators", "2026-10-07", "2026-10-08"
    )
    args.spool_root = tmp_path
    args.token_file = Path("private-token.txt")
    options = export_args(args, shop, window, label)
    assert options.platform_shop_id == "9768147009521852682"
    assert options.exclude_missing_accounts is True
    assert options.progress_file == options.spool_dir / "progress.json"


def test_idle_sample_older_than_one_minute_keeps_safe_export_window(tmp_path):
    status = tmp_path / "cross-border-4.status.json"
    status.write_text(
        json.dumps({
            "state": "stored",
            "at": (datetime.now(UTC) - timedelta(seconds=90)).isoformat(),
        }),
        encoding="utf-8",
    )
    args = Namespace(shop_label="cross-border-4", sample_status_dir=tmp_path)
    assert choose_window(_plan(), args)[2] == "cross-border-4"


def test_failed_window_cools_down_without_blocking_other_shops(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.run_auto_affiliate_exports.sample_idle_status",
        lambda *_args, **_kwargs: "stored",
    )
    plan = _plan()
    second = dict(plan["shops"][0])
    second["business_name"] = "本土店"
    second["shop_id"] = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
    plan["shops"].append(second)
    args = Namespace(
        shop_label=None, sample_status_dir=tmp_path,
        cooldowns={
            ("cross-border-4", "creators", "2026-10-07", "2026-10-08"):
            datetime.now(UTC) + timedelta(minutes=30)
        },
    )
    assert choose_window(plan, args)[2] == "local"


def test_preempted_shop_skips_all_its_missing_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.run_auto_affiliate_exports.sample_idle_status",
        lambda *_args, **_kwargs: "stored",
    )
    plan = _plan()
    plan["shops"][0]["missing"].append({
        "resource": "creators", "start": "2026-09-07", "end": "2026-10-06",
    })
    second = dict(plan["shops"][0])
    second["business_name"] = "本土店"
    second["shop_id"] = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
    plan["shops"].append(second)
    args = Namespace(
        shop_label=None, sample_status_dir=tmp_path, cooldowns={},
        shop_cooldowns={"cross-border-4": datetime.now(UTC) + timedelta(minutes=10)},
    )
    assert choose_window(plan, args)[2] == "local"


def test_recent_preemption_survives_scheduler_restart(tmp_path):
    status = tmp_path / "status.json"
    when = datetime.now(UTC)
    status.write_text(
        '{"state":"sample_priority_cancelled","shop":"cross-border-12",'
        f'"at":"{when.isoformat()}"}}', encoding="utf-8"
    )
    cooldowns = load_interruption_cooldown(status)
    assert cooldowns["cross-border-12"] > when


def test_wrong_local_shop_id_fails_closed(tmp_path):
    plan = _plan()
    plan["shops"][0]["shop_id"] = "e4408786-af60-545e-8f8c-5ef22a71e675"
    args = Namespace(spool_root=tmp_path, token_file=Path("private-token.txt"))
    with pytest.raises(RuntimeError, match="identity mismatch"):
        export_args(args, plan["shops"][0], plan["shops"][0]["missing"][0], "cross-border-4")


def test_only_one_auto_export_process_can_hold_lock(tmp_path):
    lock = tmp_path / "collector.lock"
    with (
        process_lock(lock),
        pytest.raises(RuntimeError, match="already running"),
        process_lock(lock),
    ):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["capture_timeout", "sample_priority_cancelled"])
async def test_interrupted_window_cools_so_other_shops_can_progress(monkeypatch, tmp_path, outcome):
    args = Namespace(once=False, interval_seconds=60, status_file=tmp_path / "status.json")
    window = ("cross-border-12", "creators", "2026-08-08", "2026-09-06")

    class EndPass(Exception):
        pass

    async def interrupted(current):
        current.current_window = window
        return outcome

    async def stop_after_first_pass(_):
        assert args.cooldowns[window] > datetime.now(UTC)
        raise EndPass

    monkeypatch.setattr("scripts.run_auto_affiliate_exports.run_pass", interrupted)
    monkeypatch.setattr(asyncio, "sleep", stop_after_first_pass)
    with pytest.raises(EndPass):
        await run(args)
