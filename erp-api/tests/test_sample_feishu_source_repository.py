from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_feishu_source_repository import (
    SampleFeishuSourceRecord,
    SampleFeishuSourceRepository,
    build_committed_sample_query,
)


def _row(*, tenant_id: UUID, shop_id: UUID, application_id: UUID) -> tuple[object, ...]:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    first_seen_at = datetime(2026, 9, 9, 23, 55, tzinfo=UTC)
    return (
        application_id,
        tenant_id,
        shop_id,
        "Akeleo Toys",
        "platform-application-1",
        "official_api",
        uuid4(),
        observed_at,
        first_seen_at,
        "creator-open-id",
        "creator_name",
        "Creator",
        1200,
        5_000_00,
        "USD",
        "L2",
        "PENDING",
        "product-1",
        "Product",
        "sku-1",
        "Blue",
        Decimal("0.12"),
        1,
        None,
        0,
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeSession:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def test_committed_query_is_shop_scoped_and_excludes_raw_payload() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    statement = build_committed_sample_query(
        tenant_id=tenant_id,
        shop_id=shop_id,
        after_application_id=None,
        limit=200,
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "JOIN sample_ingest_batches" in sql
    assert "sample_ingest_batches.status" in sql
    assert "sample_ingest_batches.finished_at IS NOT NULL" in sql
    assert "sample_applications.is_current_projection IS true" in sql
    assert "sample_applications.is_approvable IS true" in sql
    assert "sample_application_workflows.feishu_record_id IS NOT NULL" in sql
    assert compiled.params["status_1"] == "complete"
    assert tenant_id in compiled.params.values()
    assert shop_id in compiled.params.values()
    assert "raw_payload" not in sql
    assert "sample_applications.first_seen_at" in sql
    assert "sample_applications.tiktok_applied_at" in sql
    assert "row_number() OVER" in sql
    assert "latest_creator_metrics" in sql
    assert "creator_units_sold IS NOT NULL" in sql
    assert "LEFT OUTER JOIN affiliate_creators" in sql
    assert "creator_details_summary" in compiled.params.values()
    assert "profile_snapshot" in compiled.params.values()


def test_committed_query_can_be_limited_to_incremental_application_scope() -> None:
    application_ids = frozenset({uuid4(), uuid4()})
    statement = build_committed_sample_query(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        after_application_id=None,
        limit=200,
        application_ids=application_ids,
    )
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "sample_applications.id IN" in str(compiled)
    assert set(application_ids) in (
        set(value) for value in compiled.params.values() if isinstance(value, list)
    )


def test_committed_query_can_exclude_pre_activation_history() -> None:
    activation_at = datetime(2026, 9, 14, 9, 37, tzinfo=UTC)
    statement = build_committed_sample_query(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        after_application_id=None,
        limit=200,
        activation_at=activation_at,
    )
    compiled = statement.compile(dialect=postgresql.dialect())

    assert "sample_applications.tiktok_applied_at >=" in str(compiled)
    assert activation_at in compiled.params.values()


@pytest.mark.asyncio
async def test_repository_returns_only_projected_database_records() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    application_id = uuid4()
    session = FakeSession(
        [_row(tenant_id=tenant_id, shop_id=shop_id, application_id=application_id)]
    )
    repository = SampleFeishuSourceRepository(FakeDatabase(session))  # type: ignore[arg-type]

    records = await repository.list_committed(
        tenant_id=tenant_id,
        shop_id=shop_id,
    )

    assert records == (SampleFeishuSourceRecord(*session.rows[0]),)
    assert records[0].application_id == application_id
    assert not hasattr(records[0], "raw_payload")


def test_feishu_source_boundary_accepts_no_payload_or_browser_capture() -> None:
    parameters = inspect.signature(
        SampleFeishuSourceRepository.list_committed
    ).parameters
    source = Path("src/erp_api/services/sample_feishu_source_repository.py").read_text(
        encoding="utf-8"
    )

    assert set(parameters) == {
        "self",
        "tenant_id",
        "shop_id",
        "after_application_id",
        "limit",
        "application_ids",
    }
    assert "raw_payload" not in source
    assert "hubstudio" not in source.casefold()
    assert "backend.app" not in source


@pytest.mark.parametrize("limit", [0, 501])
def test_committed_query_rejects_unsafe_page_size(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 500"):
        build_committed_sample_query(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            after_application_id=None,
            limit=limit,
        )
