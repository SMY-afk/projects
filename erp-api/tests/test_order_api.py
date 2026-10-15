from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import ORDERS_VIEW
from erp_api.models.order import Order
from erp_api.models.shop import Shop
from erp_api.routers import orders
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.order_repository import OrderListItem, OrderListPage


class _OrderRepository:
    def __init__(self, order: Order) -> None:
        self.order = order

    async def list_orders(self, tenant_id: UUID, **kwargs) -> OrderListPage:
        return OrderListPage(
            items=[OrderListItem(order=self.order, settlement_amount_minor=900)],
            total=1,
        )

    async def get_order(self, tenant_id: UUID, order_id: UUID) -> Order | None:
        return self.order if order_id == self.order.id else None


def _order(*, with_shop: bool) -> Order:
    timestamp = datetime(2026, 8, 20, tzinfo=UTC)
    order = Order(
        id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        platform_order_id="platform-order-1",
        order_number="order-1",
        status="completed",
        external_status="COMPLETED",
        currency="USD",
        subtotal_amount_minor=1000,
        shipping_fee_minor=0,
        discount_amount_minor=0,
        tax_amount_minor=0,
        total_amount_minor=1000,
        placed_at=timestamp,
        platform_updated_at=timestamp,
        synced_at=timestamp,
    )
    order.shop = (
        Shop(
            id=order.shop_id,
            tenant_id=order.tenant_id,
            platform="tiktok",
            platform_shop_id="platform-shop-1",
            shop_name="Demo Shop",
            status="active",
        )
        if with_shop
        else None  # type: ignore[assignment]
    )
    order.lines = []
    order.fulfillments = []
    order.recipient = None
    order.attribution = None
    order.affiliate_order_items = []
    return order


def _client(order: Order) -> TestClient:
    app = FastAPI()
    app.include_router(orders.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=order.tenant_id
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Admin",
        username="admin",
        roles=[],
        permissions=[ORDERS_VIEW],
    )
    app.dependency_overrides[orders._repository] = lambda: _OrderRepository(order)
    return TestClient(app)


def test_order_list_api_returns_platform_name_from_shop_relation() -> None:
    order = _order(with_shop=True)

    with _client(order) as client:
        response = client.get("/api/orders")

    assert response.status_code == 200
    assert response.json()["items"][0]["platformName"] == "tiktok"
    assert response.json()["items"][0]["settlementAmountMinor"] == 900


def test_order_detail_api_returns_null_platform_name_without_shop() -> None:
    order = _order(with_shop=False)

    with _client(order) as client:
        response = client.get(f"/api/orders/{order.id}")

    assert response.status_code == 200
    assert response.json()["platformName"] is None
