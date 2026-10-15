"""Retained failed ARQ results must not prevent one safe sample recovery."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts import recover_deferred_sample_batch as recovery


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_success", [False, True, None])
async def test_only_failed_remote_source_job_gets_recovery_id(monkeypatch, prior_success):
    calls = []

    class Redis:
        async def enqueue_job(self, *args, **kwargs):
            calls.append((args, kwargs))
            return None if len(calls) == 1 else object()

    class Job:
        def __init__(self, *_args, **_kwargs):
            pass

        async def result_info(self):
            return None if prior_success is None else SimpleNamespace(success=prior_success)

    monkeypatch.setattr(recovery, "Job", Job)
    batch_id = uuid4()
    state = await recovery.enqueue_verified_batch(Redis(), "cross-border-3", batch_id)
    if prior_success is False:
        assert state == "RECOVERY_QUEUED"
        assert calls[1][1]["_job_id"] == f"remote-sample:{batch_id}:recovery"
        assert calls[1][0][-1] == str(batch_id)
    else:
        assert state == "ALREADY_QUEUED_OR_COMPLETE"
        assert len(calls) == 1
