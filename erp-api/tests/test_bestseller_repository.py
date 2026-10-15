from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.bestseller_repository import (
    BestsellerRepository,
    BestsellerSnapshotQuery,
)
from erp_api.services.tiktok_bestseller_schemas import (
    DesensitizedGmvRange,
    TikTokBestsellerEntry,
    TikTokBestsellerPage,
)


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, snapshot_id: UUID) -> None:
        self.snapshot_id = snapshot_id
        self.statements: list[object] = []
        self.commits = 0

    async def scalar(self, statement) -> UUID:
        self.statements.append(statement)
        return self.snapshot_id

    async def execute(self, statement) -> None:
        self.statements.append(statement)
        return SimpleNamespace(rowcount=2)

    async def commit(self) -> None:
        self.commits += 1


def _entry(rank: int, external_id: str | None = None) -> TikTokBestsellerEntry:
    return TikTokBestsellerEntry(
        entity_type="product",
        external_id=external_id or f"product-{rank}",
        rank=rank,
        display_name=f"Product {rank}",
        gmv=DesensitizedGmvRange("$1K-$2K", "USD"),
        extensions={"rating": "4.8", "nested": {"value": rank}},
        raw_payload={"id": external_id or f"product-{rank}", "private": rank},
    )


def _query(shop_id: UUID) -> BestsellerSnapshotQuery:
    return BestsellerSnapshotQuery(
        shop_id=shop_id,
        entity_type="product",
        reference_date=date(2026, 8, 19),
        time_slot="7D",
        currency="USD",
    )


def _sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_replace_snapshot_upserts_identity_then_deletes_and_inserts_whole_list() -> (
    None
):
    tenant_id, shop_id, snapshot_id = uuid4(), uuid4(), uuid4()
    session = FakeSession(snapshot_id)
    repository = BestsellerRepository(FakeDatabase(session))
    page = TikTokBestsellerPage([_entry(1), _entry(2)], "request-1")

    stored_id = asyncio.run(
        repository.replace_snapshot(tenant_id, _query(shop_id), page)
    )

    assert stored_id == snapshot_id
    assert session.commits == 1
    assert len(session.statements) == 3
    snapshot_sql, delete_sql, entry_sql = map(_sql, session.statements)
    assert "ON CONFLICT ON CONSTRAINT uq_bestseller_snapshots_query" in snapshot_sql
    assert "DELETE FROM bestseller_entries" in delete_sql
    assert "INSERT INTO bestseller_entries" in entry_sql
    assert "product-1" not in snapshot_sql
    assert "platform_request_id" in snapshot_sql
    assert "is_stale" in snapshot_sql
    assert "last_error_category" in snapshot_sql
    assert "last_error_at" in snapshot_sql
    assert False in session.statements[0].compile().params.values()
    assert "NONE" in session.statements[0].compile().params.values()
    entry_params = session.statements[2].compile().params.values()
    assert {"id": "product-1", "private": 1} in entry_params
    assert any(
        isinstance(value, datetime) and value > datetime.now(UTC) + timedelta(days=29)
        for value in entry_params
    )


def test_replacing_with_empty_top_list_still_deletes_all_old_entries() -> None:
    session = FakeSession(uuid4())
    repository = BestsellerRepository(FakeDatabase(session))

    asyncio.run(
        repository.replace_snapshot(
            uuid4(),
            _query(uuid4()),
            TikTokBestsellerPage([], "request-empty"),
        )
    )

    assert session.commits == 1
    assert len(session.statements) == 2
    assert "DELETE FROM bestseller_entries" in _sql(session.statements[1])


def test_same_query_reuses_snapshot_and_second_call_replaces_entire_first_page() -> (
    None
):
    tenant_id, shop_id, snapshot_id = uuid4(), uuid4(), uuid4()
    session = FakeSession(snapshot_id)
    repository = BestsellerRepository(FakeDatabase(session))

    first_id = asyncio.run(
        repository.replace_snapshot(
            tenant_id,
            _query(shop_id),
            TikTokBestsellerPage([_entry(1), _entry(2)], "request-1"),
        )
    )
    second_id = asyncio.run(
        repository.replace_snapshot(
            tenant_id,
            _query(shop_id),
            TikTokBestsellerPage([_entry(1, "product-3")], "request-2"),
        )
    )

    assert first_id == second_id == snapshot_id
    assert session.commits == 2
    assert len(session.statements) == 6
    assert "DELETE FROM bestseller_entries" in _sql(session.statements[4])
    second_insert_params = session.statements[5].compile().params.values()
    assert "product-3" in second_insert_params
    assert "product-1" not in second_insert_params
    assert "product-2" not in second_insert_params


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([_entry(rank) for rank in range(1, 102)], "Top 100"),
        ([_entry(1), _entry(1, "product-2")], "rank"),
        ([_entry(1), _entry(2, "product-1")], "external_id"),
    ],
)
def test_invalid_or_partial_lists_fail_before_database_write(
    entries: list[TikTokBestsellerEntry], message: str
) -> None:
    session = FakeSession(uuid4())
    repository = BestsellerRepository(FakeDatabase(session))

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            repository.replace_snapshot(
                uuid4(),
                _query(uuid4()),
                TikTokBestsellerPage(entries, "request-1"),
            )
        )

    assert session.statements == []
    assert session.commits == 0


def test_snapshot_requires_request_id_and_matching_entity_type() -> None:
    repository = BestsellerRepository(FakeDatabase(FakeSession(uuid4())))
    mismatched = TikTokBestsellerEntry(
        entity_type="video",
        external_id="video-1",
        rank=1,
        display_name=None,
        gmv=DesensitizedGmvRange("$1K-$2K", "USD"),
        extensions={},
    )

    with pytest.raises(ValueError, match="platform_request_id"):
        asyncio.run(
            repository.replace_snapshot(
                uuid4(), _query(uuid4()), TikTokBestsellerPage([], None)
            )
        )
    with pytest.raises(ValueError, match="entity_type"):
        asyncio.run(
            repository.replace_snapshot(
                uuid4(),
                _query(uuid4()),
                TikTokBestsellerPage([mismatched], "request-1"),
            )
        )


def test_author_type_is_non_null_for_every_query_identity() -> None:
    assert _query(uuid4()).normalized_author_type() == "NONE"
    creator_query = BestsellerSnapshotQuery(
        shop_id=uuid4(),
        entity_type="creator",
        reference_date=date(2026, 8, 19),
        time_slot="7D",
        currency="USD",
        author_type="AFFILIATE",
    )

    assert creator_query.normalized_author_type() == "AFFILIATE"

    with pytest.raises(ValueError, match="require"):
        BestsellerSnapshotQuery(
            shop_id=uuid4(),
            entity_type="creator",
            reference_date=date(2026, 8, 19),
            time_slot="7D",
            currency="USD",
        ).normalized_author_type()


def test_expired_raw_payload_cleanup_keeps_normalized_entry_columns() -> None:
    session = FakeSession(uuid4())
    repository = BestsellerRepository(FakeDatabase(session), raw_payload_ttl_days=7)
    now = datetime(2026, 8, 20, tzinfo=UTC)

    cleared = asyncio.run(repository.clear_expired_raw_payloads(uuid4(), now=now))

    assert cleared == 2
    assert session.commits == 1
    sql = _sql(session.statements[0])
    assert "UPDATE bestseller_entries" in sql
    assert "raw_payload=" in sql
    assert "raw_payload_expires_at=" in sql
    assert "display_name=" not in sql
    assert "extensions=" not in sql
