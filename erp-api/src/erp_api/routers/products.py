from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import PRODUCTS_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.product_detail_repository import (
    ProductDetailRepository,
    StoredProductDetail,
)
from erp_api.services.product_repository import (
    ProductListRecord,
    ProductRepository,
    ProductSyncResult,
)

router = APIRouter(prefix="/products", tags=["products"])


class ProductItem(BaseModel):
    id: str
    shopId: UUID
    name: str
    code: str
    status: str
    updatedAt: str
    owner: str
    shopName: str
    category: str
    stock: int
    imageUrl: str | None = None
    sellerSku: str | None = None
    currentPrice: str | None = None
    skus: list[ProductSkuItem] = []


class ProductSkuItem(BaseModel):
    id: UUID
    platformSkuId: str
    sellerSku: str
    stock: int
    priceMinor: int
    currency: str


class ProductListResponse(BaseModel):
    items: list[ProductItem]
    total: int
    page: int
    pageSize: int


class ProductDetailResponse(ProductItem):
    description: str | None
    imageUrls: list[str]
    categoryChain: list[str]
    packageWeight: str | None
    packageDimensions: dict[str, str]
    brand: str | None


class ProductSyncResponse(BaseModel):
    runId: UUID
    shopId: UUID
    status: str
    fetchedCount: int
    upsertedCount: int
    lastCursor: str | None
    error: str | None


def _product_repository(request: Request) -> ProductRepository:
    repository = request.app.state.product_repository
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _product_detail_repository(request: Request) -> ProductDetailRepository:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return ProductDetailRepository(database)


@router.post("/sync", response_model=ProductSyncResponse)
async def sync_products(
    request: Request,
    shop_id: UUID = Query(..., alias="shop_id"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
) -> ProductSyncResponse:
    service = request.app.state.product_sync_service
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        result: ProductSyncResult = await service.sync_products(
            session.tenant_id, shop_id=shop_id
        )
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The requested TikTok shop is not authorized for product sync.",
        ) from error
    return ProductSyncResponse(
        runId=result.run_id,
        shopId=result.shop_id,
        status=result.status,
        fetchedCount=result.fetched_count,
        upsertedCount=result.upserted_count,
        lastCursor=result.last_cursor,
        error=result.error,
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    request: Request,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(PRODUCTS_VIEW)),
    repository: ProductRepository = Depends(_product_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    keyword: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    shop_id: UUID | None = Query(None, alias="shopId"),
) -> ProductListResponse:
    page_data = await repository.list_products(
        session.tenant_id,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status_filter,
        shop_id=shop_id,
    )
    return ProductListResponse(
        items=[_to_stored_item(product) for product in page_data.items],
        total=page_data.total,
        page=page,
        pageSize=page_size,
    )


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product_detail(
    product_id: str,
    shop_id: UUID = Query(..., alias="shopId"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(PRODUCTS_VIEW)),
    repository: ProductDetailRepository = Depends(_product_detail_repository),
) -> ProductDetailResponse:
    product = await repository.get_product_detail(
        session.tenant_id, shop_id, product_id
    )
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _to_stored_detail(product)


def _to_stored_item(product: ProductListRecord) -> ProductItem:
    return ProductItem(
        id=product.platform_product_id,
        shopId=product.shop_id,
        name=product.name,
        code=product.code,
        status=product.status,
        updatedAt=product.updated_at.strftime("%Y-%m-%d %H:%M"),
        owner=product.shop_name,
        shopName=product.shop_name,
        sellerSku=product.skus[0]["sellerSku"] if product.skus else None,
        currentPrice=product.current_price,
        imageUrl=product.image_url,
        skus=[ProductSkuItem.model_validate(sku) for sku in product.skus],
        category=product.category,
        stock=product.stock,
    )


def _to_stored_detail(product: StoredProductDetail) -> ProductDetailResponse:
    return ProductDetailResponse(
        id=product.platform_product_id,
        shopId=product.shop_id,
        name=product.name,
        code=product.code,
        status=product.status,
        updatedAt=product.updated_at.strftime("%Y-%m-%d %H:%M"),
        owner=product.shop_name,
        shopName=product.shop_name,
        category=product.category,
        stock=product.stock,
        imageUrl=product.image_urls[0] if product.image_urls else None,
        sellerSku=product.seller_sku,
        currentPrice=product.current_price,
        skus=[ProductSkuItem.model_validate(sku) for sku in product.skus],
        description=product.description,
        imageUrls=product.image_urls,
        categoryChain=product.category_chain,
        packageWeight=product.package_weight,
        packageDimensions=product.package_dimensions,
        brand=product.brand,
    )
