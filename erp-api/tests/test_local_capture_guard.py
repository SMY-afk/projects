import asyncio

import pytest

from scripts import local_capture_guard as guard


def test_free_and_refundable_cannot_hold_same_shop(tmp_path):
    with guard.browser_work("cross-border-7", root=tmp_path):
        with (
            pytest.raises(guard.CaptureGuardError, match="browser_busy"),
            guard.browser_work("cross-border-7", root=tmp_path),
        ):
            pytest.fail("Concurrent browser mutation")
        with guard.browser_work("cross-border-4", root=tmp_path):
            pass


def test_captcha_pause_survives_restarting_collector(tmp_path):
    guard.pause_shop("cross-border-7", "captcha", root=tmp_path)
    with (
        pytest.raises(guard.CaptureGuardError, match="captcha"),
        guard.browser_work("cross-border-7", root=tmp_path),
    ):
        pytest.fail("Captcha must require confirmed recovery")


def test_captcha_failure_latches_shared_shop_pause(tmp_path):
    with (
        pytest.raises(RuntimeError),
        guard.browser_work("cross-border-7", root=tmp_path),
    ):
        raise RuntimeError("TikTok captcha requires operator verification.")
    assert guard.pause_reason("cross-border-7", root=tmp_path) == "captcha"


def test_restore_requires_fresh_online_verification(monkeypatch, tmp_path):
    guard.pause_shop("cross-border-7", "captcha", root=tmp_path)

    async def captcha(_endpoint):
        return "captcha"

    monkeypatch.setattr(guard, "browser_security_state", captcha)
    with pytest.raises(guard.CaptureGuardError):
        asyncio.run(guard.confirm_recovery("cross-border-7", "endpoint", root=tmp_path))
    assert guard.pause_reason("cross-border-7", root=tmp_path) == "captcha"


def test_failure_backoff_is_capped_and_busy_is_not_aggressive():
    assert guard.retry_delay(guard.CaptureGuardError("browser_busy"), 1, 300) == 60
    assert guard.retry_delay(RuntimeError("offline"), 1, 300) == 300
    assert guard.retry_delay(RuntimeError("offline"), 2, 300) == 600
    assert guard.retry_delay(RuntimeError("offline"), 10, 300) == 900


def test_five_shops_share_two_browser_capacity_slots(tmp_path):
    with guard.browser_work("cross-border-3", root=tmp_path):
        with (
            guard.browser_work("cross-border-4", root=tmp_path),
            pytest.raises(guard.CaptureGuardError, match="capture_capacity_busy"),
            guard.browser_work("cross-border-7", root=tmp_path),
        ):
            pytest.fail("Third browser mutation exceeded memory capacity")
        with guard.browser_work("cross-border-7", root=tmp_path):
            pass
    with guard.browser_work("local", root=tmp_path):
        pass
