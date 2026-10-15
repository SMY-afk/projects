import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.affiliate_repository import AffiliateRepository


class FakeResult:
    def all(self):
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult()

    async def scalar(self, statement):
        self.statements.append(statement)
        return 0


class FakeDatabase:
    def __init__(self) -> None:
        self.session_instance = FakeSession()
        self.tenant_ids = []

    async def session(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        yield self.session_instance


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_order_query_uses_tenant_shop_and_platform_order_join() -> None:
    sql = _sql(AffiliateRepository._order_select())

    assert "LEFT OUTER JOIN orders" in sql
    assert "orders.tenant_id = affiliate_order_items.tenant_id" in sql
    assert "orders.shop_id = affiliate_order_items.shop_id" in sql
    assert "orders.platform_order_id = affiliate_order_items.main_order_id" in sql


def test_order_list_uses_tenant_session_and_requested_filters() -> None:
    database = FakeDatabase()
    repository = AffiliateRepository(database)  # type: ignore[arg-type]
    tenant_id = uuid4()
    shop_id = uuid4()

    result = asyncio.run(
        repository.list_orders(
            tenant_id,
            page=2,
            page_size=25,
            shop_id=shop_id,
            main_order_id="main-1",
            creator_id="creator-1",
            created_from=datetime(2026, 8, 1, tzinfo=UTC),
            created_to=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )

    assert result.items == []
    assert result.total == 0
    assert database.tenant_ids == [tenant_id]
    list_sql = _sql(database.session_instance.statements[0])
    assert "affiliate_order_items.shop_id" in list_sql
    assert "affiliate_order_items.main_order_id = 'main-1'" in list_sql
    assert "affiliate_order_items.creator_id = 'creator-1'" in list_sql
    assert "LIMIT 25 OFFSET 25" in list_sql


def test_creator_stats_group_by_creator_and_currency() -> None:
    database = FakeDatabase()
    repository = AffiliateRepository(database)  # type: ignore[arg-type]

    result = asyncio.run(
        repository.list_creator_stats(
            uuid4(),
            page=1,
            page_size=20,
        )
    )

    assert result.items == []
    assert result.total == 0
    stats_sql = _sql(database.session_instance.statements[1])
    assert "count(distinct(affiliate_order_items.main_order_id))" in stats_sql.lower()
    assert "sum(affiliate_order_items.commission_base)" in stats_sql
    assert "sum(affiliate_order_items.estimated_standard_commission)" in stats_sql
    assert "affiliate_order_items.commission_currency" in stats_sql
