from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scripts import local_sample_metadata_remote as remote
from scripts.local_sample_metadata_state import payload_hash
from tests.test_local_sample_metadata_rules import evidence


class Lock:
    def __init__(self, _database):
        pass

    @asynccontextmanager
    async def acquire(self, *_args):
        yield True


@pytest.mark.asyncio
async def test_existing_exact_receipt_never_enriches_or_dispatches(monkeypatch):
    request = {"attempt_id": "a" * 32, "payload_hash": "a" * 64}
    receipt = {"status": "completed", "result": "metadataApplied", **request}
    monkeypatch.setattr(remote, "payload_hash", lambda *_: "a" * 64)
    request.update(manifest={}, capture={})
    monkeypatch.setattr(remote, "SampleShopSyncLock", Lock)
    monkeypatch.setattr(remote, "receipt", AsyncMock(return_value=receipt))
    enrich = AsyncMock()
    monkeypatch.setattr(remote, "SampleApplicationTimeEnrichmentService", lambda *_: SimpleNamespace(enrich=enrich))
    assert await remote.apply(None, request, None) == receipt
    enrich.assert_not_called()


@pytest.mark.asyncio
async def test_source_health_failure_is_before_any_metadata_write(monkeypatch):
    manifest, capture = evidence(datetime.now(UTC))
    digest = payload_hash(manifest, capture)
    request = {"manifest": manifest, "capture": capture,
               "attempt_id": digest[:32], "payload_hash": digest}
    monkeypatch.setattr(remote, "SampleShopSyncLock", Lock)
    monkeypatch.setattr(remote, "receipt", AsyncMock(return_value={"status": "not_found"}))
    monkeypatch.setattr(remote.SampleBusinessReadiness, "_require_readyz", AsyncMock(
        side_effect=RuntimeError("sample_business_readiness:readyz_unhealthy")))
    enrich = AsyncMock()
    monkeypatch.setattr(remote, "SampleApplicationTimeEnrichmentService", lambda *_: SimpleNamespace(enrich=enrich))
    reply = await remote.apply(None, request, None)
    assert reply["status"] == "deferred" and reply["no_metadata_write"] is True
    assert reply["reason"] == "sample_business_readiness:readyz_unhealthy"
    enrich.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_receipt_created_only_after_exact_readback(monkeypatch):
    manifest, capture = evidence(datetime.now(UTC))
    digest = payload_hash(manifest, capture)
    request = {"manifest": manifest, "capture": capture,
               "attempt_id": digest[:32], "payload_hash": digest}
    app_id = uuid4()
    enrich = AsyncMock(return_value=SimpleNamespace(
        application_ids=frozenset({app_id}), matched_count=1, updated_count=1))
    receipt_payloads = []

    class Session:
        async def execute(self, statement):
            receipt_payloads.append(statement.compile().params["after_data"])

        async def commit(self):
            pass

    @asynccontextmanager
    async def factory():
        yield Session()

    database = SimpleNamespace(system_session_factory=factory)
    monkeypatch.setattr(remote, "SampleShopSyncLock", Lock)
    monkeypatch.setattr(remote, "receipt", AsyncMock(side_effect=[
        {"status": "not_found"}, {"status": "completed"}]))
    monkeypatch.setattr(remote.SampleBusinessReadiness, "_require_readyz", AsyncMock())
    monkeypatch.setattr(remote, "preview_related", AsyncMock(return_value=({app_id}, app_id)))
    monkeypatch.setattr(remote, "verify_applied", AsyncMock())
    monkeypatch.setattr(remote, "SampleApplicationTimeEnrichmentService", lambda *_: SimpleNamespace(enrich=enrich))
    await remote.apply(database, request, None)
    assert len(receipt_payloads) == 1
    assert receipt_payloads[0]["business_dispatch"] == "original_official_worker"
    assert receipt_payloads[0]["result"] == "metadataApplied"
    assert "notification" not in receipt_payloads[0]


@pytest.mark.asyncio
async def test_readback_failure_produces_no_success_receipt(monkeypatch):
    manifest, capture = evidence(datetime.now(UTC))
    digest = payload_hash(manifest, capture)
    request = {"manifest": manifest, "capture": capture,
               "attempt_id": digest[:32], "payload_hash": digest}
    app_id = uuid4()
    monkeypatch.setattr(remote, "SampleShopSyncLock", Lock)
    receipt = AsyncMock(return_value={"status": "not_found"})
    monkeypatch.setattr(remote, "receipt", receipt)
    monkeypatch.setattr(remote.SampleBusinessReadiness, "_require_readyz", AsyncMock())
    monkeypatch.setattr(remote, "preview_related", AsyncMock(return_value=({app_id}, app_id)))
    monkeypatch.setattr(remote, "verify_applied", AsyncMock(side_effect=RuntimeError("metadata_readback_mismatch")))
    monkeypatch.setattr(remote, "SampleApplicationTimeEnrichmentService", lambda *_: SimpleNamespace(
        enrich=AsyncMock(return_value=SimpleNamespace(application_ids=frozenset({app_id})))))
    with pytest.raises(RuntimeError, match="readback_mismatch"):
        await remote.apply(None, request, None)
    assert receipt.await_count == 1


@pytest.mark.asyncio
async def test_metadata_lock_wait_releases_busy_transaction_before_retry(monkeypatch):
    events, outcomes, tick = [], iter([False, False, True]), [0.0]

    class ContendedLock:
        def __init__(self, _database):
            pass

        @asynccontextmanager
        async def acquire(self, *_args):
            acquired = next(outcomes)
            events.append(("acquire", acquired))
            try:
                yield acquired
            finally:
                events.append(("release", acquired))

    async def pause(seconds):
        assert events[-1] == ("release", False)
        tick[0] += seconds

    monkeypatch.setattr(remote, "SampleShopSyncLock", ContendedLock)
    async with remote.metadata_lock(None, wait_seconds=10, clock=lambda: tick[0], pause=pause) as acquired:
        assert acquired is True
        assert tick[0] == 4
        assert events[-1] == ("acquire", True)
    assert events[-1] == ("release", True)


@pytest.mark.asyncio
async def test_metadata_lock_wait_is_bounded_without_forcing_unlock(monkeypatch):
    attempts, tick = [], [0.0]

    class BusyLock:
        def __init__(self, _database):
            pass

        @asynccontextmanager
        async def acquire(self, *_args):
            attempts.append("try")
            yield False

    async def pause(seconds):
        tick[0] += seconds

    monkeypatch.setattr(remote, "SampleShopSyncLock", BusyLock)
    async with remote.metadata_lock(None, wait_seconds=1, clock=lambda: tick[0], pause=pause) as acquired:
        assert acquired is False
    assert tick[0] == 1
    assert len(attempts) == 2
