from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_post_source_work_gate import SamplePostSourceWorkGate


class _Gate(SamplePostSourceWorkGate):
    last_sync_at = datetime.now(UTC)
    status_change = False

    async def _has_missing_sample(self, *_args, **_kwargs) -> bool:
        return False

    async def _latest_feishu_sync_at(self, *_args, **_kwargs):
        return self.last_sync_at

    async def _has_unsynced_status_change(self, *_args, **_kwargs) -> bool:
        return self.status_change


@pytest.mark.asyncio
async def test_local_gate_skips_when_source_and_queues_are_unchanged() -> None:
    calls = []

    class Cooperation:
        async def has_pending(self, *_args, **_kwargs):
            calls.append("cooperation")
            return False

    class Assignments:
        async def has_pending(self, **_kwargs):
            calls.append("assignments")
            return False

    class Notifications:
        async def list_due(self, **_kwargs):
            calls.append("notifications")
            return []

    result = await _Gate(
        object(),
        cooperation_precheck=Cooperation(),
        auto_assignments=Assignments(),
        notifications=Notifications(),
    ).has_work(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="hubstudio_cdp",
        source_results=(SimpleNamespace(changed_application_ids=()),),
        application_ids=frozenset({uuid4()}),
        obsolete_platform_application_ids=frozenset(),
    )

    assert result is False
    assert calls == ["cooperation", "assignments", "notifications"]


@pytest.mark.asyncio
async def test_local_gate_does_not_read_feishu_for_non_actionable_source_refresh() -> (
    None
):
    changed_id = uuid4()
    gate = _Gate(object())
    for source_type in ("hubstudio_cdp", "official_api"):
        result = await gate.has_work(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            source_type=source_type,
            source_results=(SimpleNamespace(changed_application_ids=(changed_id,)),),
            application_ids=frozenset({changed_id}),
            obsolete_platform_application_ids=frozenset(),
        )
        assert result is False


@pytest.mark.asyncio
async def test_local_gate_does_not_repeat_group_cleanup_without_due_work() -> None:
    result = await _Gate(object()).has_work(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="hubstudio_cdp",
        source_results=(SimpleNamespace(application_ids=(uuid4(),)),),
        application_ids=frozenset({uuid4()}),
        obsolete_platform_application_ids=frozenset({"obsolete-application"}),
    )
    assert result is False


@pytest.mark.asyncio
async def test_local_gate_runs_for_unsynced_status_change() -> None:
    gate = _Gate(object())
    gate.status_change = True
    assert await gate.has_work(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="official_api",
        source_results=(SimpleNamespace(application_ids=(uuid4(),)),),
        application_ids=frozenset({uuid4()}),
        obsolete_platform_application_ids=frozenset(),
    )


@pytest.mark.asyncio
async def test_local_gate_refreshes_latest_window_at_least_daily() -> None:
    gate = _Gate(object())
    gate.last_sync_at = datetime.now(UTC) - timedelta(days=2)
    assert await gate.has_work(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        source_type="hubstudio_cdp",
        source_results=(SimpleNamespace(application_ids=(uuid4(),)),),
        application_ids=frozenset({uuid4()}),
        obsolete_platform_application_ids=frozenset(),
    )


@pytest.mark.asyncio
async def test_local_gate_preserves_immediate_assignment_and_notification_work() -> (
    None
):
    class Assignments:
        async def has_pending(self, **_kwargs):
            return True

    class Notifications:
        async def list_due(self, **_kwargs):
            return [(uuid4(), uuid4(), 0)]

    arguments = {
        "tenant_id": uuid4(),
        "shop_id": uuid4(),
        "source_type": "official_api",
        "source_results": (SimpleNamespace(application_ids=(uuid4(),)),),
        "application_ids": frozenset({uuid4()}),
        "obsolete_platform_application_ids": frozenset(),
    }
    assert await _Gate(object(), auto_assignments=Assignments()).has_work(**arguments)
    assert await _Gate(object(), notifications=Notifications()).has_work(**arguments)


@pytest.mark.asyncio
async def test_missing_sample_uses_committed_feishu_source_eligibility() -> None:
    class Session:
        statement = None

        async def scalar(self, statement):
            self.statement = statement

    session = Session()

    class Database:
        @asynccontextmanager
        async def system_session_factory(self):
            yield session

    activation_at = datetime(2026, 10, 4, tzinfo=UTC)
    gate = SamplePostSourceWorkGate(Database(), activation_at=activation_at)
    assert not await gate._has_missing_sample(uuid4(), uuid4(), frozenset({uuid4()}))

    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "sample_applications.is_approvable IS true" in sql
    assert "sample_applications.tiktok_applied_at >=" in sql
    assert "sample_ingest_batches.status = 'complete'" in sql
    assert "sample_ingest_batches.finished_at IS NOT NULL" in sql
    assert "refundable_contract_verified" in sql
    assert "sample_applications.sample_type = 'free'" in sql
    assert "sample_applications.sample_type = 'refundable'" in sql
