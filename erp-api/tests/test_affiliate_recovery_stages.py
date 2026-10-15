"""Recovery uploads must not retain browser locks or lose pending originals."""
import importlib.util
from argparse import Namespace
from pathlib import Path
from uuid import uuid4

import pytest


def load_recovery():
    path = Path(__file__).resolve().parents[1] / '.runtime/recover-affiliate-gaps-20261013.py'
    spec = importlib.util.spec_from_file_location('affiliate_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize('delivery_fails', [False, True])
async def test_browser_released_before_delivery_and_pending_retained(tmp_path, monkeypatch, delivery_fails):
    module = load_recovery()
    active = [False]
    folder = tmp_path / '2026-08-11_2026-09-09'
    options = Namespace(spool_dir=folder, capture=True)
    manifest = Namespace(capture_id=uuid4(), model_dump_json=lambda: '{}')
    args = Namespace(status_file=tmp_path / 'state.json')

    class Guard:
        def __enter__(self): active[0] = True
        def __exit__(self, *_): active[0] = False

    async def capture(_):
        assert active[0]
        return manifest, b'original-workbook', None

    async def secondary(_, operation): return await operation()

    async def deliver(opts):
        assert not active[0]
        assert opts.capture is False
        pending = list(folder.glob('pending-*'))
        assert len(pending) == 1
        assert (pending[0] / 'workbook.xlsx').read_bytes() == b'original-workbook'
        if delivery_fails: raise RuntimeError('transport_failed')

    monkeypatch.setattr(module, 'export_args', lambda *_: options)
    monkeypatch.setattr(module, 'browser_work', lambda _: Guard())
    monkeypatch.setattr(module, 'run_secondary', secondary)
    monkeypatch.setattr(module, 'capture_workbook', capture, raising=False)
    monkeypatch.setattr(module, 'send_export', deliver, raising=False)
    if delivery_fails:
        with pytest.raises(RuntimeError, match='transport_failed'):
            await module.staged_window(args, {}, {}, 'cross-border-3')
    else:
        assert await module.staged_window(args, {}, {}, 'cross-border-3') == 'stored'
    assert not active[0]
    assert len(list(folder.glob('pending-*'))) == 1
