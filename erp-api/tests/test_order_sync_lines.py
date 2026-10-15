import asyncio
from types import SimpleNamespace
from uuid import uuid4

from erp_api.models.order_line import OrderLine
from erp_api.services.order_sync_lines import sync_order_lines


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, existing):
        self.existing = existing
        self.added = []
        self.statements = []

    async def scalars(self, statement):
        self.statements.append(statement)
        return ScalarRows(self.existing)

    async def execute(self, statement):
        self.statements.append(statement)

    def add(self, value):
        self.added.append(value)


async def no_sku(session, shop_id, line):
    return None, None


def test_resync_updates_existing_order_line_without_replacing_its_identity() -> None:
    tenant_id, order_id, line_id = uuid4(), uuid4(), uuid4()
    existing = OrderLine(
        id=line_id,
        tenant_id=tenant_id,
        order_id=order_id,
        platform_line_id="line-1",
        product_name="Old name",
        quantity=1,
        original_unit_price_minor=100,
        sale_unit_price_minor=100,
        discount_amount_minor=0,
        line_total_amount_minor=100,
    )
    incoming = SimpleNamespace(
        platform_line_id="line-1",
        platform_product_id="product-1",
        platform_sku_id="sku-1",
        seller_sku="SELLER-1",
        product_name="Updated name",
        sku_name="Blue",
        image_url=None,
        quantity=2,
        original_unit_price_minor=200,
        sale_unit_price_minor=180,
        discount_amount_minor=20,
        line_total_amount_minor=360,
    )
    session = FakeSession([existing])

    asyncio.run(
        sync_order_lines(
            session,
            tenant_id=tenant_id,
            shop_id=uuid4(),
            order_id=order_id,
            incoming_lines=[incoming],
            resolve_sku=no_sku,
        )
    )

    assert existing.id == line_id
    assert existing.product_name == "Updated name"
    assert existing.quantity == 2
    assert not [item for item in session.added if isinstance(item, OrderLine)]
    statements = "\n".join(str(statement) for statement in session.statements)
    assert "DELETE FROM order_lines" in statements
    assert "return_request_items" in statements


def test_new_line_is_fully_resolved_before_it_is_added_to_the_session() -> None:
    tenant_id, order_id = uuid4(), uuid4()
    session = FakeSession([])
    incoming = SimpleNamespace(
        platform_line_id="new-line",
        platform_product_id=None,
        platform_sku_id=None,
        seller_sku=None,
        product_name="New product",
        sku_name=None,
        image_url=None,
        quantity=1,
        original_unit_price_minor=100,
        sale_unit_price_minor=100,
        discount_amount_minor=0,
        line_total_amount_minor=100,
    )

    async def resolve_before_add(current_session, shop_id, line):
        assert current_session.added == []
        return None, None

    asyncio.run(
        sync_order_lines(
            session,
            tenant_id=tenant_id,
            shop_id=uuid4(),
            order_id=order_id,
            incoming_lines=[incoming],
            resolve_sku=resolve_before_add,
        )
    )

    assert len(session.added) == 1
    assert session.added[0].product_name == "New product"
