import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.services import sample_raw_capture_retry as retry_module
from backend.app.services.sample_queue_backpressure import put_with_backpressure
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_watch_error_category import (
    requires_cdp_rediscovery,
)
from erp_api.services.sample_raw_capture_lock import (
    SampleRawCaptureLock,
    sample_raw_capture_lock_key,
)

OBSERVED_AT = datetime(2026, 10, 9, 1, tzinfo=UTC)


def _persist(
    store: SampleRawBatchStore,
    sequence: int,
    page_sequence: int,
    request_page: int,
    has_more: bool,
) -> None:
    store.persist_page(
        sequence,
        page_sequence,
        {"agg_info": []},
        request_id=f"request-{request_page}",
        request_page=request_page,
        request_cursor=f'[["cur_page",{request_page}]]',
        response_has_more=has_more,
        response_total_count=0,
        response_observed_at=OBSERVED_AT,
    )


def test_missing_request_page_is_rejected_before_downstream(tmp_path: Path) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    sequence = store.start_batch()
    _persist(store, sequence, 1, 1, True)
    _persist(store, sequence, 2, 3, False)

    with pytest.raises(RuntimeError, match="request pages are not contiguous"):
        store.complete_batch(
            sequence,
            2,
            expected_total=0,
            captured_total=0,
            terminal_confirmed=True,
        )


def test_incomplete_batch_is_preserved_as_abandoned_evidence(tmp_path: Path) -> None:
    store = SampleRawBatchStore(tmp_path, "shop-123")
    sequence = store.start_batch()
    _persist(store, sequence, 1, 1, True)

    assert store.abandon_capturing("capture_restarted") == 1
    manifest = json.loads(
        (tmp_path / "shop-123" / f"batch-{sequence:012d}" / "manifest.json")
        .read_text("utf-8")
    )
    assert manifest["status"] == "abandoned"
    assert manifest["reason"] == "capture_restarted"
    assert store.recover_completed() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("RAW batch request pages are not contiguous"),
        ConnectionError("CDP connection closed"),
    ],
)
async def test_retry_replays_entire_batch_after_gap_or_disconnect(
    monkeypatch, failure: Exception
) -> None:
    calls: list[object] = []
    expected = object()

    class Store:
        def abandon_capturing(self, reason: str) -> int:
            calls.append(("abandon", reason))
            return 1

    async def capture(*_args, **_kwargs):
        calls.append("capture")
        if calls.count("capture") == 1:
            raise failure
        return expected

    async def sleep(seconds: float) -> None:
        calls.append(("sleep", seconds))

    async def security_state(_endpoint):
        return "online"

    monkeypatch.setattr(retry_module, "capture_review_batch", capture)
    monkeypatch.setattr(retry_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(retry_module, "browser_security_state", security_state)

    result = await retry_module.capture_review_batch_with_retry(
        "http://127.0.0.1:1234",
        "shop",
        Store(),
        timeout_seconds=30,
    )

    assert result is expected
    assert calls[0] == "capture"
    assert calls[1][0] == "abandon"
    assert calls[-1] == "capture"


@pytest.mark.asyncio
async def test_backpressure_waits_without_dropping_item() -> None:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
    await queue.put("first")

    pending = asyncio.create_task(put_with_backpressure(queue, "second"))
    await asyncio.sleep(0)
    assert not pending.done()
    assert await queue.get() == "first"
    await pending
    assert await queue.get() == "second"


class FakeConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired

    async def scalar(self, _statement):
        return self.acquired


class FakeEngine:
    def __init__(self, acquired: bool) -> None:
        self.connection = FakeConnection(acquired)

    @asynccontextmanager
    async def begin(self):
        yield self.connection


@pytest.mark.asyncio
async def test_same_shop_capture_lock_rejects_second_browser() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    assert sample_raw_capture_lock_key(
        tenant_id, shop_id
    ) == sample_raw_capture_lock_key(tenant_id, shop_id)
    lock = SampleRawCaptureLock(
        type("Database", (), {"engine": FakeEngine(False)})()
    )

    async with lock.acquire(tenant_id, shop_id) as acquired:
        assert acquired is False


def test_runner_holds_capture_claim_through_business_processing() -> None:
    source = Path("scripts/run_hubstudio_raw_sample_watch.py").read_text("utf-8")
    acquire = source.index("capture_lock.acquire")
    capture = source.index("capture = await capture_review_batch_with_retry")
    downstream = source.index("pipeline.complete_after_source")

    assert acquire < capture < downstream
    assert "duplicate_capture_prevented" in source


def test_disconnect_requires_process_recycle_for_cdp_rediscovery() -> None:
    assert requires_cdp_rediscovery(ConnectionError("CDP connection closed"))
    assert requires_cdp_rediscovery(
        RuntimeError("Target page, context or browser has been closed")
    )
    assert not requires_cdp_rediscovery(RuntimeError("expected total changed"))
