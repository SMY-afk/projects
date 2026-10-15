import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from scripts import sample_capture_priority as priority
from scripts.local_capture_guard import CaptureGuardError


def test_wait_does_not_even_create_secondary_browser_operation(tmp_path):
    called = []

    async def operation():
        called.append(True)

    with pytest.raises(CaptureGuardError, match="free_priority_wait"):
        asyncio.run(priority.run_secondary("cross-border-7", operation, root=tmp_path))
    assert not called


def test_free_arrival_cancels_only_secondary_operation_and_runs_cleanup(tmp_path):
    cleaned = []

    async def operation():
        try:
            priority.request_free("cross-border-7", root=tmp_path)
            await asyncio.Event().wait()
        finally:
            cleaned.append(True)

    priority.finish_free(
        "cross-border-7",
        True,
        datetime.now(UTC) + timedelta(seconds=300),
        root=tmp_path,
    )
    with pytest.raises(CaptureGuardError, match="free_priority_wait"):
        asyncio.run(priority.run_secondary("cross-border-7", operation, root=tmp_path))
    assert cleaned == [True]
