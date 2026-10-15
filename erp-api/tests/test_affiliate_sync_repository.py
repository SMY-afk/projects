import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.affiliate_sync_repository import AffiliateSyncRepository
from erp_api.services.order_evidence_repository import EvidenceIngestResult


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
    def __init__(self, returned_keys) -> None:
        self.returned_keys = returned_keys
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.returned_keys)

    async def commit(self):
        self.commits += 1


class FakeDatabase:
    def __init__(self, returned_keys) -> None:
        self.session_instance = FakeSession(returned_keys)
        self.tenant_ids = []

    async def session(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        yield self.session_instance


class FakeEvidenceRepository:
    def __init__(self) -> None:
        self.calls = []

    async def ingest_affiliate_records(self, session, tenant_id, shop_id, records):
        self.calls.append((session, tenant_id, shop_id, records))
        return EvidenceIngestResult(len(records), len(records), 0)


def _repository(database):
    repository = AffiliateSyncRepository(database)  # type: ignore[arg-type]
    repository._evidence_repository = FakeEvidenceRepository()
    return repository


def _record(source_key: str = "source-1") -> dict[str, object]:
    return {
        "main_order_id": "main-1",
        "creator_id": "creator-1",
        "creator_nickname": "Creator One",
        "campaign_id": "campaign-1",
        "product_id": "product-1",
        "product_name": "Product One",
        "image_uri": "https://example.test/image.jpg",
        "sku_id": "sku-1",
        "sku_name": None,
        "order_created_at": datetime(2026, 8, 18, tzinfo=UTC),
        "is_cod": False,
        "is_non_same_shop_order": False,
        "cos_type": "1",
        "commission_base": Decimal("10.00"),
        "commission_currency": "USD",
        "commission_rate": Decimal("0.15"),
        "estimated_standard_commission": Decimal("1.50"),
        "source_record_key": source_key,
        "raw_data": {"source": "fixture"},
    }


def test_bulk_upsert_writes_orders_and_success_state_in_one_commit() -> None:
    database = FakeDatabase(["source-1"])
    repository = _repository(database)
    tenant_id = uuid4()
    shop_id = uuid4()

    result = asyncio.run(
        repository.bulk_upsert(
            tenant_id,
            shop_id,
            [_record()],
            next_cursor="cursor-1",
            has_more=True,
        )
    )

    assert result.received_count == 1
    assert result.unique_count == 1
    assert result.upserted_count == 1
    assert database.session_instance.commits == 1
    assert len(database.session_instance.statements) == 2
    order_sql = str(
        database.session_instance.statements[0].compile(dialect=postgresql.dialect())
    )
    state_sql = str(
        database.session_instance.statements[1].compile(dialect=postgresql.dialect())
    )
    assert (
        "ON CONFLICT ON CONSTRAINT "
        "uq_affiliate_order_items_shop_source_record DO UPDATE"
    ) in order_sql
    assert "affiliate_order_items.tenant_id = excluded.tenant_id" in order_sql
    assert (
        "ON CONFLICT ON CONSTRAINT uq_affiliate_sync_states_shop DO UPDATE" in state_sql
    )
    assert "affiliate_sync_states.tenant_id = excluded.tenant_id" in state_sql


def test_bulk_upsert_deduplicates_source_key_inside_page() -> None:
    database = FakeDatabase(["source-1"])
    repository = _repository(database)
    first = _record()
    second = {**first, "product_name": "Updated Product"}

    result = asyncio.run(
        repository.bulk_upsert(
            uuid4(),
            uuid4(),
            [first, second],
            next_cursor=None,
            has_more=False,
        )
    )

    assert result.received_count == 2
    assert result.unique_count == 1
    assert result.upserted_count == 1


def test_empty_page_still_updates_success_state() -> None:
    database = FakeDatabase([])
    repository = _repository(database)

    result = asyncio.run(
        repository.bulk_upsert(
            uuid4(),
            uuid4(),
            [],
            next_cursor=None,
            has_more=False,
        )
    )

    assert result.upserted_count == 0
    assert len(database.session_instance.statements) == 1
    assert database.session_instance.commits == 1
