import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.routers.products import get_product_detail


class FakeProductDetailRepository:
    def __init__(self, detail) -> None:
        self.detail = detail
        self.calls = []

    async def get_product_detail(self, tenant_id, shop_id, product_id):
        self.calls.append((tenant_id, shop_id, product_id))
        return self.detail


def test_product_detail_route_reads_only_the_local_repository() -> None:
    tenant_id, shop_id, sku_id = uuid4(), uuid4(), uuid4()
    detail = SimpleNamespace(
        shop_id=shop_id,
        platform_product_id="product-1",
        name="Local product",
        code="SELLER-1",
        status="ACTIVATE",
        updated_at=datetime(2026, 8, 20, 7, 0, tzinfo=UTC),
        shop_name="Akeleo Fun Toys",
        category="US",
        stock=4,
        image_urls=["https://cdn.example/product-1.jpg"],
        seller_sku="SELLER-1",
        current_price="USD 9.50",
        skus=[
            {
                "id": sku_id,
                "platformSkuId": "sku-1",
                "sellerSku": "SELLER-1",
                "stock": 4,
                "priceMinor": 950,
                "currency": "USD",
            }
        ],
        description="<p>Stored description</p>",
        category_chain=["Toys", "Vehicles"],
        package_weight="1.2 kg",
        package_dimensions={"length": "10", "width": "5"},
        brand="Akeleo",
    )
    repository = FakeProductDetailRepository(detail)

    response = asyncio.run(
        get_product_detail(
            product_id="product-1",
            shop_id=shop_id,
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,
        )
    )

    assert repository.calls == [(tenant_id, shop_id, "product-1")]
    assert response.name == "Local product"
    assert response.description == "<p>Stored description</p>"
    assert response.imageUrls == ["https://cdn.example/product-1.jpg"]
    assert response.skus[0].platformSkuId == "sku-1"
