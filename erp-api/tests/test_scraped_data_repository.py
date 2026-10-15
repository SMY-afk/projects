import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.scraped_data_repository import (
    ScrapedDataOwnershipConflict,
    ScrapedDataRepository,
    ScrapedDataUpsertError,
)


class FakeScalarResult:
    def __init__(self, values) -> None:
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, values) -> None:
        self._values = values

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, returned_platform_ids) -> None:
        self.returned_platform_ids = returned_platform_ids
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.returned_platform_ids)

    async def commit(self):
        self.commits += 1


class FakeDatabase:
    def __init__(self, returned_platform_ids) -> None:
        self.session_instance = FakeSession(returned_platform_ids)
        self.tenant_ids = []

    async def session(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        yield self.session_instance


def _record(platform_id: str = "affiliate_order:main-1:sku-1") -> dict[str, object]:
    return {
        "platform_id": platform_id,
        "data_type": "affiliate_order",
        "creator_id": "creator-1",
        "creator_name": "Creator One",
        "title": "Product One",
        "raw_data": {"source": "fixture"},
    }


def test_bulk_upsert_uses_one_postgresql_statement_and_commits() -> None:
    platform_id = "affiliate_order:main-1:sku-1"
    database = FakeDatabase([platform_id])
    repository = ScrapedDataRepository(database)  # type: ignore[arg-type]
    tenant_id = uuid4()

    result = asyncio.run(repository.bulk_upsert(tenant_id, [_record()]))

    assert result.received_count == 1
    assert result.unique_count == 1
    assert result.upserted_count == 1
    assert database.tenant_ids == [tenant_id]
    assert database.session_instance.commits == 1
    assert len(database.session_instance.statements) == 1
    sql = str(
        database.session_instance.statements[0].compile(dialect=postgresql.dialect())
    )
    assert "ON CONFLICT ON CONSTRAINT uq_scraped_data_platform_id DO UPDATE" in sql
    assert "scraped_data.tenant_id = excluded.tenant_id" in sql
    assert "RETURNING scraped_data.platform_id" in sql


def test_bulk_upsert_deduplicates_same_platform_id_inside_batch() -> None:
    platform_id = "affiliate_order:main-1:sku-1"
    database = FakeDatabase([platform_id])
    repository = ScrapedDataRepository(database)  # type: ignore[arg-type]
    first = _record(platform_id)
    second = {**first, "title": "Updated title"}

    result = asyncio.run(repository.bulk_upsert(uuid4(), [first, second]))

    assert result.received_count == 2
    assert result.unique_count == 1
    assert result.upserted_count == 1


def test_bulk_upsert_rejects_cross_tenant_platform_conflict() -> None:
    database = FakeDatabase([])
    repository = ScrapedDataRepository(database)  # type: ignore[arg-type]

    with pytest.raises(ScrapedDataOwnershipConflict):
        asyncio.run(repository.bulk_upsert(uuid4(), [_record()]))

    assert database.session_instance.commits == 0


def test_bulk_upsert_rejects_missing_raw_json() -> None:
    repository = ScrapedDataRepository(FakeDatabase([]))  # type: ignore[arg-type]
    record = _record()
    record.pop("raw_data")

    with pytest.raises(ScrapedDataUpsertError, match="raw_data must be an object"):
        asyncio.run(repository.bulk_upsert(uuid4(), [record]))
