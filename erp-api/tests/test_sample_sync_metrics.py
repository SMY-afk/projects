from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.main import create_app
from erp_api.routers.sample_applications import list_sample_sync_metrics
from erp_api.services.sample_sync_metrics_repository import (
    SampleSyncMetrics,
    sample_sync_metrics_statement,
)


class FakeStatusRepository:
    async def shop_exists(self, tenant_id, shop_id):
        return True


class FakeMetricsRepository:
    def __init__(self, row) -> None:
        self.row = row
        self.call = None

    async def list_metrics(self, tenant_id, **filters):
        self.call = (tenant_id, filters)
        return [self.row]


def test_metrics_route_returns_tenant_scoped_operational_counts() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    now = datetime(2026, 9, 10, 3, tzinfo=UTC)
    row = SampleSyncMetrics(
        shop_id=shop_id,
        shop_name="Test Shop",
        sync_type="source_to_postgres",
        source_type="official_api",
        run_count=8,
        queued_count=1,
        succeeded_count=5,
        partial_count=1,
        failed_count=1,
        running_count=0,
        records_read=120,
        records_created=10,
        records_updated=20,
        feishu_created=0,
        feishu_updated=0,
        average_duration_seconds=3.5,
        last_succeeded_at=now,
        last_failed_at=now,
    )
    repository = FakeMetricsRepository(row)

    response = asyncio.run(
        list_sample_sync_metrics(
            shop_id=shop_id,
            sync_type="source_to_postgres",
            source_type="official_api",
            window_hours=24,
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            status_repository=FakeStatusRepository(),
            metrics_repository=repository,
        )
    )

    assert response[0].runCount == 8
    assert response[0].queuedCount == 1
    assert response[0].recordsRead == 120
    assert response[0].averageDurationSeconds == 3.5
    assert repository.call[0] == tenant_id


def test_metrics_query_is_tenant_shop_and_time_window_scoped() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    cutoff = datetime(2026, 9, 9, 3, tzinfo=UTC)
    statement = sample_sync_metrics_statement(
        tenant_id,
        cutoff=cutoff,
        shop_id=shop_id,
        sync_type="reconciliation",
        source_type="official_api",
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "sample_sync_runs.tenant_id" in sql
    assert "shops.tenant_id" in sql
    assert "sample_sync_runs.shop_id" in sql
    assert "sample_sync_runs.started_at >=" in sql
    assert "GROUP BY" in sql
    assert tenant_id in compiled.params.values()
    assert shop_id in compiled.params.values()
    assert cutoff in compiled.params.values()


def test_metrics_route_is_registered() -> None:
    assert "/api/sample-applications/metrics" in {
        route.path for route in create_app().routes
    }
