from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from erp_api.main import create_app
from erp_api.routers.sample_applications import list_sample_sync_status
from erp_api.services.sample_sync_status_repository import (
    SampleSyncStatus,
    recent_sample_sync_runs_statement,
)


class FakeRepository:
    def __init__(self, row: SampleSyncStatus, *, shop_exists: bool = True) -> None:
        self.row = row
        self.exists = shop_exists
        self.calls: list[tuple] = []

    async def shop_exists(self, tenant_id, shop_id):
        self.calls.append(("shop_exists", tenant_id, shop_id))
        return self.exists

    async def list_recent(self, tenant_id, **filters):
        self.calls.append(("list_recent", tenant_id, filters))
        return [self.row]


def _status_row() -> SampleSyncStatus:
    started_at = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
    return SampleSyncStatus(
        run_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Test Shop",
        sync_type="source_to_postgres",
        source_type="official_api",
        status="succeeded",
        pages_read=2,
        records_read=25,
        records_created=3,
        records_updated=4,
        feishu_created=0,
        feishu_updated=0,
        error_code=None,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=9),
    )


def test_recent_status_route_is_tenant_scoped_and_exposes_safe_counts() -> None:
    tenant_id = uuid4()
    row = _status_row()
    repository = FakeRepository(row)

    response = asyncio.run(
        list_sample_sync_status(
            shop_id=row.shop_id,
            sync_type="source_to_postgres",
            source_type="official_api",
            limit=10,
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,
        )
    )

    assert response[0].runId == row.run_id
    assert response[0].recordsRead == 25
    assert response[0].durationSeconds == 9
    assert response[0].model_dump().keys().isdisjoint(
        {"errorSummary", "platformRequestIds", "sourceBatchIds", "rawPayload"}
    )
    assert repository.calls == [
        ("shop_exists", tenant_id, row.shop_id),
        (
            "list_recent",
            tenant_id,
            {
                "shop_id": row.shop_id,
                "sync_type": "source_to_postgres",
                "source_type": "official_api",
                "limit": 10,
            },
        ),
    ]


def test_recent_status_hides_missing_or_other_tenant_shop() -> None:
    row = _status_row()
    repository = FakeRepository(row, shop_exists=False)

    with pytest.raises(HTTPException, match="Shop was not found") as raised:
        asyncio.run(
            list_sample_sync_status(
                shop_id=row.shop_id,
                sync_type=None,
                source_type=None,
                limit=20,
                session=SimpleNamespace(tenant_id=uuid4()),
                _=SimpleNamespace(),
                repository=repository,
            )
        )

    assert raised.value.status_code == 404
    assert all(call[0] != "list_recent" for call in repository.calls)


def test_recent_status_query_filters_tenant_shop_and_orders_newest_first() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    statement = recent_sample_sync_runs_statement(
        tenant_id,
        shop_id=shop_id,
        sync_type="reconciliation",
        source_type="official_api",
        limit=7,
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "sample_sync_runs.tenant_id" in sql
    assert "shops.tenant_id" in sql
    assert "sample_sync_runs.shop_id" in sql
    assert "ORDER BY sample_sync_runs.started_at DESC" in sql
    assert tenant_id in compiled.params.values()
    assert shop_id in compiled.params.values()
    assert compiled.params["param_1"] == 7


def test_recent_status_route_is_registered() -> None:
    assert "/api/sample-applications/sync-status" in {
        route.path for route in create_app().routes
    }
