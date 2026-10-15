from types import SimpleNamespace

import pytest

from erp_api.workers.sample_feishu_maintenance_jobs import (
    BD_INVITATION_REFRESH_LOCK,
    cleanup_bd_invitation_protection_job,
)


class _Redis:
    def __init__(self):
        self.lock = None

    async def set(self, key, value, *, nx, ex):
        assert key == BD_INVITATION_REFRESH_LOCK
        assert nx and ex > 0
        if self.lock is not None:
            return False
        self.lock = value
        return True

    async def eval(self, script, key_count, key, owner):
        assert key_count == 1 and key == BD_INVITATION_REFRESH_LOCK
        if self.lock == owner:
            self.lock = None
            return 1
        return 0


@pytest.mark.asyncio
async def test_cleanup_lock_skips_overlapping_runs_and_releases_own_lock() -> None:
    redis = _Redis()
    calls = []

    async def refresh(*, save_ai_snapshot):
        assert save_ai_snapshot
        calls.append(1)
        return SimpleNamespace(deleted_count=2)

    ctx = {
        "redis": redis,
        "sample_bd_invitation_protection_service": SimpleNamespace(refresh=refresh),
    }
    redis.lock = "another-run"
    assert await cleanup_bd_invitation_protection_job(ctx) == 0
    assert calls == []
    assert redis.lock == "another-run"

    redis.lock = None
    assert await cleanup_bd_invitation_protection_job(ctx) == 2
    assert calls == [1]
    assert redis.lock is None
