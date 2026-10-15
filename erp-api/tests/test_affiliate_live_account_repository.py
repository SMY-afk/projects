import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.affiliate_live_account_repository import (
    AffiliateLiveAccountRepository,
    seller_live_metrics,
)


class FakeResult:
    def __init__(self, *, one=None, rows=()) -> None:
        self._one = one
        self._rows = rows

    def one(self):
        return self._one

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return FakeResult(one=(126, datetime(2026, 9, 3, tzinfo=UTC)))
        return FakeResult(rows=())


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_live_account_page_counts_and_offsets_the_filtered_query() -> None:
    session = FakeSession()
    repository = AffiliateLiveAccountRepository(FakeDatabase(session))
    tenant_id, shop_id = uuid4(), uuid4()

    result = asyncio.run(
        repository.list_page(
            tenant_id,
            shop_id,
            page=3,
            page_size=50,
            sort_by="gmv",
            sort_order="desc",
            account_type="AFFILIATE_ACCOUNTS",
            window_start=datetime(2026, 7, 1, tzinfo=UTC),
            window_end=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )

    count_sql, page_sql = map(_sql, session.statements)
    assert result.total == 126
    assert "count(tiktok_live_sessions.id)" in count_sql
    assert "AFFILIATE_ACCOUNTS" in count_sql
    assert "LIMIT 50 OFFSET 100" in page_sql
    assert "AFFILIATE_ACCOUNTS" in page_sql
    assert "ORDER BY" in page_sql


def test_seller_live_metrics_maps_views_and_ctr_for_the_requested_shop() -> None:
    payloads = [
        {
            "data": {
                "infos": [
                    {
                        "shop_id": "shop-1",
                        "live_meta": {"id": "live-1"},
                        "stats": {"views": "574", "ctr": "0.0417"},
                    },
                    {
                        "shop_id": "shop-2",
                        "live_meta": {"id": "live-2"},
                        "stats": {"views": "999", "ctr": "0.99"},
                    },
                ]
            }
        }
    ]

    assert seller_live_metrics(
        payloads,
        platform_shop_id="shop-1",
        live_ids={"live-1", "live-2"},
    ) == {
        "live-1": {"views": "574", "clickThroughRate": "0.0417"},
    }
