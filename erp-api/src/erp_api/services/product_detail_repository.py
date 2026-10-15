from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.product import Product
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.media_image_repository import resolve_product_images
from erp_api.services.product_repository import format_current_price
from erp_api.services.tiktok_schemas import (
    TikTokProductDetail,
    TikTokSku,
    parse_product_detail_response,
)
from erp_api.services.tiktok_transport import TikTokApiError


@dataclass(frozen=True)
class StoredProductDetail:
    shop_id: UUID
    platform_product_id: str
    name: str
    code: str
    status: str
    updated_at: datetime
    shop_name: str
    category: str
    stock: int
    image_urls: list[str]
    seller_sku: str | None
    current_price: str | None
    skus: list[dict[str, object]]
    description: str | None
    category_chain: list[str]
    package_weight: str | None
    package_dimensions: dict[str, str]
    brand: str | None


class ProductDetailRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_product_detail(
        self, tenant_id: UUID, shop_id: UUID, product_id: str
    ) -> StoredProductDetail | None:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(Product, Shop.shop_name)
                    .options(selectinload(Product.skus))
                    .join(Shop, Shop.id == Product.shop_id)
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Product.tenant_id == tenant_id,
                        Product.shop_id == shop_id,
                        Product.platform_product_id == product_id,
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                        ShopConnection.auth_status == "authorized",
                    )
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                return None
            product, shop_name = row
            detail = _parse_detail(product.raw_payload)
            skus = _stored_skus(product, detail)
            image_urls = list(detail.image_urls) if detail else []
            fallback = (
                await resolve_product_images(session, shop_id, [product_id])
            ).get(product_id)
            if fallback and fallback not in image_urls:
                image_urls.append(fallback)
            return StoredProductDetail(
                shop_id=product.shop_id,
                platform_product_id=product.platform_product_id,
                name=product.name,
                code=product.code,
                status=product.status,
                updated_at=product.updated_at,
                shop_name=shop_name,
                category=product.category,
                stock=product.stock,
                image_urls=image_urls,
                seller_sku=str(skus[0]["sellerSku"]) if skus else None,
                current_price=format_current_price(skus),
                skus=skus,
                description=detail.description if detail else None,
                category_chain=detail.category_chain if detail else [],
                package_weight=_package_weight(detail),
                package_dimensions=detail.package_dimensions if detail else {},
                brand=detail.brand if detail else None,
            )
        raise RuntimeError("Tenant database session was not created.")


def _parse_detail(raw_payload: dict[str, object] | None) -> TikTokProductDetail | None:
    if not raw_payload:
        return None
    try:
        return parse_product_detail_response(raw_payload)
    except TikTokApiError:
        return None


def _stored_skus(
    product: Product, detail: TikTokProductDetail | None
) -> list[dict[str, object]]:
    if product.skus:
        return [
            {
                "id": sku.id,
                "platformSkuId": sku.platform_sku_id,
                "sellerSku": sku.name,
                "stock": sku.stock,
                "priceMinor": sku.price_minor,
                "currency": sku.currency,
            }
            for sku in product.skus
        ]
    return (
        [_detail_sku(product.platform_product_id, sku) for sku in detail.skus]
        if detail
        else []
    )


def _detail_sku(product_id: str, sku: TikTokSku) -> dict[str, object]:
    try:
        price_minor = round(float(sku.price_amount or 0) * 100)
    except ValueError:
        price_minor = 0
    return {
        "id": uuid5(NAMESPACE_URL, f"{product_id}:{sku.platform_sku_id}"),
        "platformSkuId": sku.platform_sku_id,
        "sellerSku": sku.seller_sku or sku.platform_sku_id,
        "stock": max(0, sku.inventory_quantity or 0),
        "priceMinor": price_minor,
        "currency": (sku.currency or "USD").upper()[:3],
    }


def _package_weight(detail: TikTokProductDetail | None) -> str | None:
    if detail is None or not detail.package_weight_value:
        return None
    return " ".join(
        value
        for value in (detail.package_weight_value, detail.package_weight_unit)
        if value
    )
