import asyncio
from uuid import uuid4

from sqlalchemy import select

from erp_api.models.order import Order
from erp_api.services.order_repository import OrderRepository
from erp_api.services.token_cipher import TokenCipher


class _EmptyScalarResult:
    def all(self) -> list[Order]:
        return []


class _FakeSession:
    def __init__(self) -> None:
        self.list_statement = None
        self.scalar_statements = []

    async def scalars(self, statement):
        self.list_statement = statement
        return _EmptyScalarResult()

    async def execute(self, statement):
        self.list_statement = statement
        return []

    async def scalar(self, statement):
        self.scalar_statements.append(statement)


class _FakeDatabase:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


def _repository(session: _FakeSession) -> OrderRepository:
    return OrderRepository(
        _FakeDatabase(session),  # type: ignore[arg-type]
        TokenCipher("test-only-order-repository-key-1234"),
    )


def _loaded_relationship_paths(statement) -> set[str]:
    return {str(option.path) for option in statement._with_options}


def test_list_order_query_loads_shop_relation() -> None:
    session = _FakeSession()

    asyncio.run(
        _repository(session).list_orders(
            uuid4(),
            page=1,
            page_size=20,
        )
    )

    paths = _loaded_relationship_paths(session.list_statement)
    assert any("Order.shop" in path for path in paths)
    sql = str(session.list_statement)
    assert "finance_transactions" in sql
    assert "finance_transactions.is_estimated IS false" in sql


def test_detail_order_query_loads_shop_relation() -> None:
    session = _FakeSession()

    asyncio.run(_repository(session).get_order(uuid4(), uuid4()))

    paths = _loaded_relationship_paths(session.scalar_statements[0])
    assert any("Order.shop" in path for path in paths)


def test_order_filters_include_attribution_dimensions_before_pagination() -> None:
    filters = OrderRepository._filters(
        uuid4(),
        None,
        None,
        None,
        None,
        traffic_source="paid_ads",
        operator_subject="creator",
        entry_point="video",
        special_order_type="normal",
        classification_status="confirmed",
        content_form="video",
    )

    statement = select(Order).where(*filters)
    sql = str(statement)
    assert "order_attributions.traffic_source" in sql
    assert "order_attributions.operator_subject" in sql
    assert "order_attributions.entry_point" in sql
    assert "order_attributions.special_order_type" in sql
    assert "order_attributions.classification_status" in sql
    assert "affiliate_order_items.content_form" in sql


def test_unknown_attribution_filter_keeps_orders_without_a_relation() -> None:
    filters = OrderRepository._filters(
        None,
        None,
        None,
        None,
        None,
        traffic_source="unknown",
        operator_subject=None,
        entry_point=None,
        special_order_type=None,
        classification_status=None,
        content_form=None,
    )

    sql = str(select(Order).where(*filters))
    assert "NOT (EXISTS" in sql


def test_sample_order_filter_uses_zero_order_total_before_pagination() -> None:
    filters = OrderRepository._filters(
        None,
        None,
        None,
        None,
        None,
        traffic_source=None,
        operator_subject=None,
        entry_point=None,
        special_order_type="sample",
        classification_status=None,
        content_form=None,
    )

    sql = str(select(Order).where(*filters))
    assert "orders.total_amount_minor" in sql
    assert "orders.total_amount_minor =" in sql
    assert "order_attributions.special_order_type" not in sql
