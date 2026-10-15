"""Completed cron deduplication leases do not mean active daily work."""

import asyncio
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
from arq import connections

from erp_api.core import config


def probe(monkeypatch, *, payload, queued=0):
    namespace = runpy.run_path(str(Path(__file__).parents[1] / '.runtime' /
                                  'daily-cleanup-20261014' / 'deploy_daily_cleanup.py'))
    source = namespace['PROBE'].removesuffix('asyncio.run(main())\n')
    source = source.replace('asyncio.run(main())', '')
    context = {}

    class Redis:
        async def scan_iter(self, *, match, count):
            if ':cron:' in match:
                yield b'arq:in-progress:cron:enqueue_due_valid_creator_syncs:1'

        async def exists(self, key):
            assert key == 'arq:job:cron:enqueue_due_valid_creator_syncs:1'
            return payload

        async def zcard(self, _):
            return queued

        async def aclose(self):
            pass

    async def pool(_):
        return Redis()

    monkeypatch.setattr(connections, 'create_pool', pool)
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(redis_url='redis://localhost'))
    exec(source, context)  # noqa: S102 - Exercise only this trusted static deployment probe.
    asyncio.run(context['main']())


@pytest.mark.parametrize(('payload', 'expected'), [(False, 0), (True, 1)])
def test_daily_idle_distinguishes_completed_cron_lease(monkeypatch, capsys, payload, expected):
    probe(monkeypatch, payload=payload)
    output = json.loads(capsys.readouterr().out)
    assert output['busy'] == expected
