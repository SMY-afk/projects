from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.models.affiliate_creator_detail import AffiliateCreatorDetailItem
from erp_api.models.order import Order
from erp_api.models.order_line import OrderLine
from erp_api.models.product import Product
from erp_api.models.scraped_data import ScrapedData

_PRODUCT_IMAGE_DATA_TYPES = (
    "seller_product_catalog",
    "seller_product_analytics",
    "seller_video_analytics",
    "affiliate_order",
)


async def resolve_product_images(
    session: AsyncSession,
    shop_id: UUID,
    product_ids: Iterable[str],
) -> dict[str, str]:
    wanted = {value for value in product_ids if value}
    if not wanted:
        return {}
    result: dict[str, str] = {}
    product_rows = (
        await session.execute(
            select(Product.platform_product_id, Product.raw_payload).where(
                Product.shop_id == shop_id,
                Product.platform_product_id.in_(wanted),
            )
        )
    ).all()
    for product_id, raw_payload in product_rows:
        stored = raw_payload or {}
        image_url = _first_https(stored.get("main_images") or stored.get("image_urls"))
        if image_url:
            result[product_id] = image_url

    scraped_rows = (
        await session.execute(
            select(ScrapedData.data_type, ScrapedData.raw_data)
            .where(ScrapedData.data_type.in_(_PRODUCT_IMAGE_DATA_TYPES))
            .order_by(ScrapedData.updated_at.desc())
            .limit(1000)
        )
    ).all()
    for data_type, raw_data in scraped_rows:
        for product_id, image_url in extract_product_images(
            data_type, raw_data
        ).items():
            if product_id in wanted:
                result.setdefault(product_id, image_url)

    order_rows = (
        await session.execute(
            select(OrderLine.platform_product_id, OrderLine.image_url)
            .join(Order, Order.id == OrderLine.order_id)
            .where(
                Order.shop_id == shop_id,
                OrderLine.platform_product_id.in_(wanted),
                OrderLine.image_url.is_not(None),
            )
        )
    ).all()
    for product_id, image_url in order_rows:
        if product_id and (parsed := _first_https(image_url)):
            result.setdefault(product_id, parsed)
    return result


async def resolve_video_covers(
    session: AsyncSession,
    shop_id: UUID,
    video_ids: Iterable[str],
) -> dict[str, str]:
    wanted = {value for value in video_ids if value}
    if not wanted:
        return {}
    detail_rows = (
        await session.execute(
            select(
                AffiliateCreatorDetailItem.platform_content_id,
                AffiliateCreatorDetailItem.identity,
            )
            .where(
                AffiliateCreatorDetailItem.shop_id == shop_id,
                AffiliateCreatorDetailItem.platform_content_id.in_(wanted),
            )
            .order_by(AffiliateCreatorDetailItem.captured_at.desc())
        )
    ).all()
    result: dict[str, str] = {}
    for video_id, identity in detail_rows:
        if image_url := _first_https((identity or {}).get("coverImageUrl")):
            result.setdefault(video_id, image_url)

    rows = (
        await session.execute(
            select(ScrapedData.raw_data)
            .where(ScrapedData.data_type == "seller_video_analytics")
            .order_by(ScrapedData.updated_at.desc())
            .limit(100)
        )
    ).scalars()
    for raw_data in rows:
        for video_id, image_url in extract_video_covers(raw_data).items():
            if video_id in wanted:
                result.setdefault(video_id, image_url)
    return result


def extract_product_images(
    data_type: str,
    raw_data: Mapping[str, object],
) -> dict[str, str]:
    if data_type == "seller_product_catalog":
        data = _mapping(raw_data.get("data"))
        result: dict[str, str] = {}
        for raw_item in _list(data.get("products")):
            item = _mapping(raw_item)
            product_id = _text(item.get("product_id"))
            image_url = _first_https(item.get("image"))
            if product_id and image_url:
                result.setdefault(product_id, image_url)
        return result
    if data_type == "seller_product_analytics":
        data = _mapping(raw_data.get("data"))
        return _images_from_items(data.get("items"), meta_key="meta")
    if data_type == "seller_video_analytics":
        result: dict[str, str] = {}
        for value in _walk_mappings(raw_data):
            for product_id, image_url in _images_from_items(
                value.get("product_list")
            ).items():
                result.setdefault(product_id, image_url)
        return result
    if data_type == "affiliate_order":
        base = _mapping(raw_data.get("sku_order_base_info_for_affiliate_seller"))
        product = _mapping(base.get("product_info"))
        product_id = _text(product.get("product_id"))
        image_url = _first_https(product.get("url_list"))
        return {product_id: image_url} if product_id and image_url else {}
    return {}


def extract_video_covers(raw_data: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in _walk_mappings(raw_data):
        video = _mapping(value.get("video_meta"))
        video_id = _text(video.get("id"))
        image_url = _first_https(video.get("cover_image"))
        if video_id and image_url:
            result.setdefault(video_id, image_url)
    return result


def _images_from_items(
    value: object,
    *,
    meta_key: str | None = None,
) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(value, list):
        return result
    for raw_item in value:
        item = _mapping(raw_item)
        source = _mapping(item.get(meta_key)) if meta_key else item
        product_id = _text(source.get("product_id") or source.get("id"))
        image_url = _first_https(
            source.get("product_image") or source.get("image_url") or source.get("img")
        )
        if product_id and image_url:
            result.setdefault(product_id, image_url)
    return result


def _first_https(value: object) -> str | None:
    if isinstance(value, str):
        return value if value.startswith("https://") else None
    if isinstance(value, list):
        return next((url for item in value if (url := _first_https(item))), None)
    if isinstance(value, Mapping):
        for key in (
            "thumb_uri",
            "url",
            "image_url",
            "uri",
            "urls",
            "url_list",
            "thumb_url_list",
        ):
            if url := _first_https(value.get(key)):
                return url
    return None


def _walk_mappings(value: object):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None
