import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.finance_repository import FinanceQuery, FinanceRepository
from erp_api.services.finance_repository_queries import transaction_filters


def _sql(filters: list[object]) -> str:
    return " ".join(
        str(
            item.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for item in filters
    )


def test_transaction_filters_are_applied_before_pagination_query() -> None:
    query = FinanceQuery(
        shop_id=uuid4(),
        currency="usd",
        status="settled",
        transaction_type="order",
        statement_id=uuid4(),
        order_id=uuid4(),
        keyword="order-123",
        window_from=datetime(2026, 8, 1, tzinfo=UTC),
        window_to=datetime(2026, 8, 21, tzinfo=UTC),
    )

    sql = _sql(transaction_filters(query))

    assert "finance_transactions.shop_id" in sql
    assert "finance_transactions.currency = 'USD'" in sql
    assert "finance_transactions.status = 'settled'" in sql
    assert "finance_transactions.transaction_type = 'order'" in sql
    assert "finance_transactions.statement_id" in sql
    assert "finance_transactions.order_id" in sql
    assert "finance_transactions.occurred_at >=" in sql
    assert "finance_transactions.occurred_at <" in sql
    assert "ILIKE" in sql


def test_empty_keyword_does_not_add_a_search_filter() -> None:
    assert transaction_filters(FinanceQuery(keyword="  ")) == []


def test_transaction_payment_state_filters_match_the_displayed_order_states() -> None:
    pending_sql = _sql(transaction_filters(FinanceQuery(payment_state="pending")))
    refunded_sql = _sql(transaction_filters(FinanceQuery(payment_state="refunded")))
    completed_sql = _sql(transaction_filters(FinanceQuery(payment_state="completed")))

    assert "finance_transactions.is_estimated IS true" in pending_sql
    assert "upper(finance_transactions.status) = 'UNSETTLED'" in pending_sql
    assert "finance_transactions.refund_amount_minor != 0" in refunded_sql
    assert "finance_transactions.refund_amount_minor = 0" in completed_sql
    assert "finance_transactions.is_estimated IS false" in refunded_sql
    assert "finance_transactions.is_estimated IS false" in completed_sql


class _EmptyResult:
    def all(self):
        return []


class _EmptySession:
    async def execute(self, statement):
        return _EmptyResult()

    async def scalar(self, statement):
        return 0


class _CapturingDatabase:
    def __init__(self) -> None:
        self.tenant_ids = []

    async def session(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        yield _EmptySession()


def test_repository_always_opens_a_tenant_scoped_session() -> None:
    database = _CapturingDatabase()
    repository = FinanceRepository(database)  # type: ignore[arg-type]
    tenant_id = uuid4()

    result = asyncio.run(
        repository.list_transactions(
            tenant_id, page=1, page_size=20, query=FinanceQuery()
        )
    )

    assert result.total == 0
    assert database.tenant_ids == [tenant_id]
