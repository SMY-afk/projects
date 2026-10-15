import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.product_repository import (
    AuthorizedTikTokShop,
    ProductRepository,
    ProductSyncResult,
)
from erp_api.services.product_sync_service import ProductSyncService
from erp_api.services.tiktok_schemas import (
    TikTokProduct,
    TikTokProductDetail,
    TikTokProductPage,
    TikTokSku,
)
from erp_api.services.tiktok_transport import TikTokApiError


class FakeProductRepository:
    def __init__(self, shop: AuthorizedTikTokShop | None) -> None:
        self.shop = shop
        self.products: dict[str, TikTokProduct] = {}
        self.pages: list[tuple[str, int, int]] = []
        self.failure: str | None = None
        self.refreshes = []
        self.run_id = uuid4()

    async def get_authorized_tiktok_shop(self, tenant_id, shop_id):
        del tenant_id
        if shop_id is not None and (self.shop is None or shop_id != self.shop.id):
            return None
        return self.shop

    async def create_sync_run(self, tenant_id, shop_id):
        del tenant_id, shop_id
        return self.run_id

    async def upsert_product_page(
        self, tenant_id, run_id, shop_id, products, next_cursor
    ):
        del tenant_id, run_id, shop_id
        for product in products:
            self.products[product.platform_product_id] = product
        self.pages.append((next_cursor, len(products), len(products)))
        return len(products)

    async def complete_sync_run(self, tenant_id, run_id):
        del tenant_id
        return ProductSyncResult(run_id, self.shop.id, "succeeded", 2, 2, "", None)

    async def update_connection_tokens(self, tenant_id, shop_id, tokens):
        self.refreshes.append((tenant_id, shop_id, tokens))
        return True

    async def fail_sync_run(self, tenant_id, run_id, error):
        del tenant_id
        self.failure = error
        return ProductSyncResult(run_id, self.shop.id, "failed", 0, 0, None, error)


class FakeTikTokClient:
    def __init__(
        self, pages=None, error: Exception | None = None, details=None
    ) -> None:
        self.pages = pages or []
        self.error = error
        self.details = details or {}
        self.tokens: list[str] = []
        self.refresh_tokens: list[str] = []
        self.detail_ids: list[str] = []

    async def refresh_access_token(self, refresh_token):
        self.refresh_tokens.append(refresh_token)
        from erp_api.services.tiktok_client import TikTokTokenSet

        return TikTokTokenSet(
            "refreshed-access", "refreshed-refresh", 3600, ["product.read"]
        )

    async def iter_product_pages(self, access_token, **kwargs):
        self.tokens.append(access_token)
        if self.error:
            raise self.error
        for page in self.pages:
            yield page

    async def get_product_detail(self, access_token, **kwargs):
        product_id = kwargs["product_id"]
        self.detail_ids.append(product_id)
        if product_id in self.details:
            return self.details[product_id]
        product = next(
            product
            for page in reversed(self.pages)
            for product in page.products
            if product.platform_product_id == product_id
        )
        return TikTokProductDetail(
            **product.__dict__,
            description=None,
            category_chain=[],
            package_weight_value=None,
            package_weight_unit=None,
            package_dimensions={},
            brand=None,
            raw_payload={"id": product_id, "title": product.name, "skus": []},
        )


class ResumeTikTokClient(FakeTikTokClient):
    def __init__(
        self, pages, error: TikTokApiError, *, failures_remaining: int = 1
    ) -> None:
        super().__init__(pages=pages)
        self.resume_error = error
        self.page_tokens: list[str | None] = []
        self.failures_remaining = failures_remaining

    async def iter_product_pages(self, access_token, **kwargs):
        self.tokens.append(access_token)
        page_token = kwargs.get("page_token")
        self.page_tokens.append(page_token)
        if page_token is None:
            yield self.pages[0]
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise self.resume_error
        if page_token == "page-2":
            yield self.pages[1]


def _shop() -> AuthorizedTikTokShop:
    return AuthorizedTikTokShop(
        id=uuid4(),
        platform_shop_id="shop-1",
        access_token="access-secret",
        shop_cipher="cipher-secret",
    )


def _product(name: str) -> TikTokProduct:
    return TikTokProduct(
        platform_product_id="product-1",
        name=name,
        status="ACTIVATE",
        create_time=None,
        sales_regions=["US"],
        skus=[TikTokSku("sku-1", "SELLER-1", "9.50", "USD", 4)],
        image_urls=["https://cdn.example/product-1.jpg"],
    )


def test_sync_is_idempotent_and_saves_each_page_cursor() -> None:
    repository = FakeProductRepository(_shop())
    client = FakeTikTokClient(
        [
            TikTokProductPage([_product("Old name")], "page-2", 1),
            TikTokProductPage([_product("New name")], "", 1),
        ]
    )
    service = ProductSyncService(repository, client)

    first = asyncio.run(service.sync_products(uuid4(), shop_id=repository.shop.id))
    second = asyncio.run(service.sync_products(uuid4(), shop_id=repository.shop.id))

    assert first.status == second.status == "succeeded"
    assert list(repository.products) == ["product-1"]
    assert repository.products["product-1"].name == "New name"
    assert repository.pages == [
        ("page-2", 1, 1),
        ("", 1, 1),
        ("page-2", 1, 1),
        ("", 1, 1),
    ]
    assert client.tokens == ["access-secret", "access-secret"]


@pytest.mark.parametrize("error_code", ["36009003", "invalid_product_response"])
def test_sync_resumes_from_committed_cursor_after_retryable_tiktok_502(
    error_code: str,
) -> None:
    repository = FakeProductRepository(_shop())
    first = TikTokProductPage([_product("First")], "page-2", 2)
    second_product = replace(
        _product("Second"),
        platform_product_id="product-2",
        skus=[TikTokSku("sku-2", "SELLER-2", "12.00", "USD", 3)],
    )
    second = TikTokProductPage([second_product], "", 2)
    client = ResumeTikTokClient(
        [first, second],
        TikTokApiError(
            "TikTok API rejected the request.",
            code=error_code,
            status_code=502,
        ),
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(
        ProductSyncService(
            repository,
            client,
            max_resume_retries=3,
            retry_base_seconds=5,
            sleep=sleep,
        ).sync_products(uuid4(), shop_id=repository.shop.id)
    )

    assert result.status == "succeeded"
    assert client.page_tokens == [None, "page-2"]
    assert repository.pages == [("page-2", 1, 1), ("", 1, 1)]
    assert set(repository.products) == {"product-1", "product-2"}
    assert delays == [5.0]


def test_sync_fails_after_bounded_retries_without_replaying_committed_page() -> None:
    repository = FakeProductRepository(_shop())
    first = TikTokProductPage([_product("First")], "page-2", 2)
    second = TikTokProductPage([], "", 2)
    client = ResumeTikTokClient(
        [first, second],
        TikTokApiError(
            "TikTok API rejected the request.",
            code="36009003",
            status_code=502,
        ),
        failures_remaining=3,
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(
        ProductSyncService(
            repository,
            client,
            max_resume_retries=2,
            retry_base_seconds=5,
            sleep=sleep,
        ).sync_products(uuid4(), shop_id=repository.shop.id)
    )

    assert result.status == "failed"
    assert client.page_tokens == [None, "page-2", "page-2"]
    assert repository.pages == [("page-2", 1, 1)]
    assert delays == [5.0, 10.0]


def test_sync_records_sanitized_failure_without_credentials() -> None:
    repository = FakeProductRepository(_shop())
    client = FakeTikTokClient(
        error=RuntimeError(
            "request access_token=access-secret auth_code=one-time-code "
            "refresh token is another-secret authorization code 'another-code'"
        )
    )
    service = ProductSyncService(repository, client)

    result = asyncio.run(service.sync_products(uuid4(), shop_id=repository.shop.id))

    assert result.status == "failed"
    assert repository.failure is not None
    assert "access-secret" not in repository.failure
    assert "one-time-code" not in repository.failure
    assert "another-secret" not in repository.failure
    assert "another-code" not in repository.failure
    assert "[REDACTED]" in repository.failure


def test_sync_requires_an_authorized_shop() -> None:
    service = ProductSyncService(FakeProductRepository(None), FakeTikTokClient())

    with pytest.raises(RuntimeError, match="authorized TikTok shop"):
        asyncio.run(service.sync_products(uuid4(), shop_id=uuid4()))


def test_sync_passes_requested_shop_id_to_repository_and_client() -> None:
    shop = _shop()
    repository = FakeProductRepository(shop)
    client = FakeTikTokClient([TikTokProductPage([_product("Selected shop")], "", 1)])
    service = ProductSyncService(repository, client)

    result = asyncio.run(service.sync_products(uuid4(), shop_id=shop.id))

    assert result.status == "succeeded"
    assert client.tokens == ["access-secret"]


def test_sync_enriches_products_with_official_main_images() -> None:
    shop = _shop()
    repository = FakeProductRepository(shop)
    listed = replace(_product("Official detail"), image_urls=[])
    detailed = replace(listed, image_urls=["https://cdn.example/product-1.jpg"])
    detail = TikTokProductDetail(
        **detailed.__dict__,
        description=None,
        category_chain=[],
        package_weight_value=None,
        package_weight_unit=None,
        package_dimensions={},
        brand=None,
        raw_payload={
            "id": listed.platform_product_id,
            "main_images": [{"url_list": ["https://cdn.example/product-1.jpg"]}],
        },
    )
    client = FakeTikTokClient(
        [TikTokProductPage([listed], "", 1)],
        details={listed.platform_product_id: detail},
    )

    result = asyncio.run(
        ProductSyncService(repository, client).sync_products(uuid4(), shop_id=shop.id)
    )

    assert result.status == "succeeded"
    assert client.detail_ids == [listed.platform_product_id]
    assert repository.products[listed.platform_product_id].image_urls == [
        "https://cdn.example/product-1.jpg"
    ]


def test_sync_refreshes_full_detail_even_when_list_has_images() -> None:
    shop = _shop()
    repository = FakeProductRepository(shop)
    listed = _product("List product")
    detail = TikTokProductDetail(
        **listed.__dict__,
        description="<p>Full detail</p>",
        category_chain=["Toys"],
        package_weight_value="1.2",
        package_weight_unit="kg",
        package_dimensions={"length": "10"},
        brand="Akeleo",
        raw_payload={
            "id": listed.platform_product_id,
            "description": "<p>Full detail</p>",
        },
    )
    client = FakeTikTokClient(
        [TikTokProductPage([listed], "", 1)],
        details={listed.platform_product_id: detail},
    )

    result = asyncio.run(
        ProductSyncService(repository, client).sync_products(uuid4(), shop_id=shop.id)
    )

    assert result.status == "succeeded"
    assert client.detail_ids == [listed.platform_product_id]
    assert (
        repository.products[listed.platform_product_id].description
        == "<p>Full detail</p>"
    )


def test_product_upsert_preserves_official_main_images_payload() -> None:
    listed = replace(_product("Official raw"), image_urls=[])
    detail = TikTokProductDetail(
        **listed.__dict__,
        description=None,
        category_chain=[],
        package_weight_value=None,
        package_weight_unit=None,
        package_dimensions={},
        brand=None,
        raw_payload={
            "id": listed.platform_product_id,
            "main_images": [{"uri": "tos/product-1"}],
        },
    )

    statement = ProductRepository._product_upsert(uuid4(), uuid4(), detail)

    assert statement.compile().params["raw_payload"]["main_images"] == [
        {"uri": "tos/product-1"}
    ]


def test_sync_refreshes_expired_access_token_before_reading_products() -> None:
    shop = replace(
        _shop(),
        refresh_token="refresh-secret",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    repository = FakeProductRepository(shop)
    client = FakeTikTokClient([TikTokProductPage([_product("Refreshed")], "", 1)])

    result = asyncio.run(
        ProductSyncService(repository, client).sync_products(uuid4(), shop_id=shop.id)
    )

    assert result.status == "succeeded"
    assert client.refresh_tokens == ["refresh-secret"]
    assert client.tokens == ["refreshed-access"]
    assert repository.refreshes[0][2].access_token == "refreshed-access"


def test_product_upsert_bounds_platform_strings_to_database_columns() -> None:
    product = TikTokProduct(
        platform_product_id="p" * 150,
        name="n" * 250,
        status="s" * 40,
        create_time=None,
        sales_regions=["r" * 250],
        skus=[TikTokSku("sku-1", "c" * 150, "1.00", "USD", 1)],
        image_urls=[],
    )

    statement = ProductRepository._product_upsert(uuid4(), uuid4(), product)
    values = statement.compile().params

    assert len(values["platform_product_id"]) == 128
    assert len(values["name"]) == 200
    assert len(values["code"]) == 100
    assert len(values["status"]) == 32
    assert len(values["category"]) == 200


def test_product_code_falls_back_to_sku_id_not_product_id() -> None:
    product = replace(
        _product("No seller SKU"),
        skus=[TikTokSku("sku-1", None, "9.50", "USD", 4)],
    )

    statement = ProductRepository._product_upsert(uuid4(), uuid4(), product)

    assert statement.compile().params["code"] == "sku-1"
