import asyncio
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.order_logistics_projection import project_order_to_logistics


class FakeSession:
    def __init__(self, scalar_values):
        self.scalar_values = list(scalar_values)
        self.added = []
        self.flushes = 0

    async def scalar(self, statement):
        return self.scalar_values.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1


def _order(status="awaiting_shipment", external_status="AWAITING_SHIPMENT"):
    line = SimpleNamespace(
        id=uuid4(),
        platform_product_id="product-1",
        platform_sku_id="sku-1",
        seller_sku="SELLER-1",
        product_name="Product",
        sku_name="Default",
        quantity=2,
    )
    return SimpleNamespace(
        id=uuid4(),
        order_number="ORDER-1",
        shop_id=uuid4(),
        status=status,
        external_status=external_status,
        lines=[line],
    )


def test_new_awaiting_shipment_order_creates_one_pending_dispatch_task() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    order = _order()
    session = FakeSession([order, None, actor_id])

    asyncio.run(project_order_to_logistics(session, tenant_id, order.id))

    assert len(session.added) == 1
    task = session.added[0]
    assert task.status == "pending_dispatch"
    assert task.created_by_user_id == actor_id
    assert len(task.items) == 1
    assert task.items[0].packed_quantity == 2
    assert task.items[0].shipped_quantity == 0
    assert [item.operation_type for item in task.operations] == ["order_sync_projected"]

    repeated = FakeSession([order, task])
    asyncio.run(project_order_to_logistics(repeated, tenant_id, order.id))

    assert repeated.added == []
    assert len(task.items) == 1
    assert len(task.operations) == 1


def test_existing_task_advances_without_status_regression() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    order = _order("awaiting_collection", "AWAITING_COLLECTION")
    initial = FakeSession([order, None, actor_id])
    asyncio.run(project_order_to_logistics(initial, tenant_id, order.id))
    task = initial.added[0]

    order.status = "in_transit"
    order.external_status = "IN_TRANSIT"
    asyncio.run(
        project_order_to_logistics(FakeSession([order, task]), tenant_id, order.id)
    )

    assert task.status == "in_transit"
    assert task.items[0].shipped_quantity == 2
    assert len(task.operations) == 2

    order.status = "awaiting_collection"
    order.external_status = "AWAITING_COLLECTION"
    asyncio.run(
        project_order_to_logistics(FakeSession([order, task]), tenant_id, order.id)
    )

    assert task.status == "in_transit"
    assert len(task.operations) == 2


def test_terminal_historical_order_does_not_create_a_new_task() -> None:
    order = _order("completed", "COMPLETED")
    session = FakeSession([order, None])

    asyncio.run(project_order_to_logistics(session, uuid4(), order.id))

    assert session.added == []
