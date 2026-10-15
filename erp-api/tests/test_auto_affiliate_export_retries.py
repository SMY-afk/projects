"""Failed shop windows must not monopolize the five-shop collector."""
import asyncio
from argparse import Namespace
from datetime import UTC, datetime

import pytest

from scripts.affiliate_export_runtime_state import load_interruption_cooldown
from scripts.local_capture_guard import CaptureGuardError
from scripts.run_auto_affiliate_exports import run


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [RuntimeError('source failed'),
                                  CaptureGuardError('secondary_timeout')])
async def test_failed_shop_yields_all_its_windows(monkeypatch, tmp_path, error):
    args = Namespace(once=False, interval_seconds=30,
                     status_file=tmp_path / 'status.json')
    window = ('cross-border-4', 'creators', '2026-09-11', '2026-10-10')

    class StopPass(Exception):
        pass

    async def fail(current):
        current.current_shop = window[0]
        current.current_resource = window[1]
        current.current_window = window
        raise error

    async def stop(_):
        assert args.cooldowns[window] > datetime.now(UTC)
        assert args.shop_cooldowns[window[0]] > datetime.now(UTC)
        assert load_interruption_cooldown(args.status_file)[window[0]] > datetime.now(UTC)
        raise StopPass

    monkeypatch.setattr('scripts.run_auto_affiliate_exports.run_pass', fail)
    monkeypatch.setattr(asyncio, 'sleep', stop)
    with pytest.raises(StopPass):
        await run(args)
