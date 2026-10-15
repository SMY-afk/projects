import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from erp_api.main import app
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.routers.affiliate import (
    get_affiliate_order,
    list_affiliate_orders,
    list_creator_stats,
)
from erp_api.services.affiliate_repository import (
    AffiliateOrderPage,
    AffiliateOrderRecord,
    CreatorStats,
    CreatorStatsPage,
)


def _record() -> AffiliateOrderRecord:
    created_at = datetime(2026, 8, 18, tzinfo=UTC)
    return AffiliateOrderRecord(
        item=AffiliateOrderItem(
            id=uuid4(),
            tenant_id=uuid4(),
            shop_id=uuid4(),
            main_order_id="main-1",
            creator_id="creator-1",
            creator_nickname="Creator One",
            campaign_id="campaign-1",
            product_id="product-1",
            product_name="Product One",
            image_uri="https://example.test/product.png",
            sku_id="sku-1",
            sku_name="Red",
            order_created_at=created_at,
            is_cod=False,
            is_non_same_shop_order=False,
            cos_type="standard",
            promotion_id="9371233970479993847",
            promotion_type=2,
            content_form="video",
            commission_base=Decimal("100.0000"),
            commission_currency="USD",
            commission_rate=Decimal("0.100000"),
            estimated_standard_commission=Decimal("10.0000"),
            raw_data={},
            source_record_key="source-1",
        ),
        order_id=uuid4(),
        order_number="ORDER-1",
        order_status="completed",
    )


class FakeRepository:
    def __init__(self, *, records=None) -> None:
        self.records = records if records is not None else [_record()]
        self.calls = []

    async def list_orders(self, tenant_id, **kwargs):
        self.calls.append(("list", tenant_id, kwargs))
        return AffiliateOrderPage(items=self.records, total=len(self.records))

    async def get_order(self, tenant_id, main_order_id, **kwargs):
        self.calls.append(("detail", tenant_id, main_order_id, kwargs))
        return self.records

    async def list_creator_stats(self, tenant_id, **kwargs):
        self.calls.append(("stats", tenant_id, kwargs))
        return CreatorStatsPage(
            items=[
                CreatorStats(
                    creator_id="creator-1",
                    creator_nickname="Creator One",
                    commission_currency="USD",
                    order_count=3,
                    item_count=4,
                    commission_base=Decimal("200.0000"),
                    estimated_standard_commission=Decimal("20.0000"),
                    last_order_at=datetime(2026, 8, 18, tzinfo=UTC),
                )
            ],
            total=1,
        )


def test_three_affiliate_get_routes_are_registered() -> None:
    paths = {
        route.path for route in app.routes if "GET" in getattr(route, "methods", set())
    }

    assert "/api/affiliate/orders" in paths
    assert "/api/affiliate/orders/{main_order_id}" in paths
    assert "/api/affiliate/creators/stats" in paths
    assert app.state.affiliate_repository is not None


def test_affiliate_order_list_maps_order_link_and_exact_money() -> None:
    repository = FakeRepository()
    tenant_id = uuid4()

    response = asyncio.run(
        list_affiliate_orders(
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,  # type: ignore[arg-type]
            page=1,
            page_size=20,
            shop_id=None,
            main_order_id=None,
            creator_id=None,
            created_from=None,
            created_to=None,
        )
    )

    assert response.total == 1
    assert response.items[0].mainOrderId == "main-1"
    assert response.items[0].orderNumber == "ORDER-1"
    assert response.items[0].creatorNickname == "Creator One"
    assert response.items[0].promotionId == "9371233970479993847"
    assert response.items[0].promotionType == 2
    assert response.items[0].contentForm == "video"
    assert response.items[0].contentFormLabel == "视频"
    assert response.items[0].estimatedStandardCommission == Decimal("10.0000")
    assert repository.calls[0][1] == tenant_id


def test_affiliate_order_detail_returns_all_sku_items() -> None:
    records = [_record(), _record()]
    repository = FakeRepository(records=records)

    response = asyncio.run(
        get_affiliate_order(
            main_order_id="main-1",
            session=SimpleNamespace(tenant_id=uuid4()),
            _=SimpleNamespace(),
            repository=repository,  # type: ignore[arg-type]
            shop_id=None,
        )
    )

    assert response.mainOrderId == "main-1"
    assert len(response.items) == 2


def test_affiliate_order_detail_returns_404_when_missing() -> None:
    repository = FakeRepository(records=[])

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            get_affiliate_order(
                main_order_id="missing",
                session=SimpleNamespace(tenant_id=uuid4()),
                _=SimpleNamespace(),
                repository=repository,  # type: ignore[arg-type]
                shop_id=None,
            )
        )

    assert raised.value.status_code == 404


def test_creator_stats_maps_grouped_totals() -> None:
    repository = FakeRepository()

    response = asyncio.run(
        list_creator_stats(
            session=SimpleNamespace(tenant_id=uuid4()),
            _=SimpleNamespace(),
            repository=repository,  # type: ignore[arg-type]
            page=1,
            page_size=20,
            shop_id=None,
            created_from=None,
            created_to=None,
        )
    )

    assert response.total == 1
    assert response.items[0].creatorId == "creator-1"
    assert response.items[0].orderCount == 3
    assert response.items[0].itemCount == 4
    assert response.items[0].estimatedStandardCommission == Decimal("20.0000")
