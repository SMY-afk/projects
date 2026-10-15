from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from sqlalchemy import or_, select

from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.product import Product
from erp_api.services.affiliate_avatar_cache_policy import retained_avatar
from erp_api.services.affiliate_video_cover_storage import (
    presign_stored_video_covers,
)
from erp_api.services.media_image_repository import (
    resolve_product_images,
    resolve_video_covers,
)


async def enrich_video_media(
    session,
    shop_id: UUID,
    items: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    rows = list(items)
    usernames = {
        normalized
        for item in rows
        if (normalized := _normalize_username(item.get("creatorUsername")))
    }
    open_ids = {value for item in rows if (value := _text(item.get("creatorOpenId")))}
    product_ids = _product_ids(rows)
    video_ids = {
        value
        for item in rows
        if (value := _text(item.get("videoId") or item.get("id")))
    }

    avatars_by_username: dict[str, str] = {}
    avatars_by_open_id: dict[str, str] = {}
    if usernames or open_ids:
        conditions = []
        if usernames:
            conditions.append(AffiliateCreator.username_normalized.in_(usernames))
        if open_ids:
            conditions.append(AffiliateCreator.creator_open_id.in_(open_ids))
        creator_rows = (
            await session.execute(
                select(
                    AffiliateCreator.username_normalized,
                    AffiliateCreator.creator_open_id,
                    AffiliateCreator.avatar_url,
                ).where(
                    AffiliateCreator.shop_id == shop_id,
                    AffiliateCreator.avatar_url.is_not(None),
                    or_(*conditions),
                )
            )
        ).all()
        for username, open_id, avatar_url in creator_rows:
            if not avatar_url:
                continue
            if username:
                avatars_by_username[username] = avatar_url
            if open_id:
                avatars_by_open_id[open_id] = avatar_url

    products_by_id: dict[str, str] = {}
    if product_ids:
        product_rows = (
            await session.execute(
                select(Product.platform_product_id, Product.name).where(
                    Product.shop_id == shop_id,
                    Product.platform_product_id.in_(product_ids),
                )
            )
        ).all()
        products_by_id = {
            product_id: name for product_id, name in product_rows if product_id and name
        }

    product_images = await resolve_product_images(session, shop_id, product_ids)
    video_covers = await resolve_video_covers(session, shop_id, video_ids)
    video_covers.update(await presign_stored_video_covers(rows))
    return [
        merge_video_media(
            item,
            avatars_by_username=avatars_by_username,
            avatars_by_open_id=avatars_by_open_id,
            products_by_id=products_by_id,
            product_images=product_images,
            video_covers=video_covers,
        )
        for item in rows
    ]


def merge_video_media(
    item: Mapping[str, object],
    *,
    avatars_by_username: Mapping[str, str],
    avatars_by_open_id: Mapping[str, str],
    products_by_id: Mapping[str, str],
    product_images: Mapping[str, str],
    video_covers: Mapping[str, str],
) -> dict[str, object]:
    merged = dict(item)
    video_id = _text(item.get("videoId") or item.get("id"))
    username = _normalize_username(item.get("creatorUsername"))
    open_id = _text(item.get("creatorOpenId"))
    merged["creatorAvatarUrl"] = retained_avatar(
        avatars_by_open_id.get(open_id or "") or avatars_by_username.get(username or ""),
        _text(item.get("creatorAvatarUrl")),
    )
    stored_cover = (
        video_covers.get(video_id or "")
        if _text(item.get("coverImageObjectKey"))
        else None
    )
    merged["coverImageUrl"] = (
        stored_cover
        or _text(item.get("coverImageUrl"))
        or video_covers.get(video_id or "")
    )
    merged["promotedProducts"] = _merged_products(
        item,
        products_by_id,
        product_images,
    )
    return merged


def _merged_products(
    item: Mapping[str, object],
    titles: Mapping[str, str],
    images: Mapping[str, str],
) -> list[dict[str, object]]:
    existing: dict[str, Mapping[str, object]] = {}
    raw_products = item.get("promotedProducts")
    if isinstance(raw_products, list):
        for product in raw_products:
            if isinstance(product, Mapping) and (
                product_id := _text(product.get("productId") or product.get("id"))
            ):
                existing[product_id] = product
    ordered_ids = list(existing)
    raw_ids = item.get("promotedProductIds")
    if isinstance(raw_ids, list):
        for raw_id in raw_ids:
            if (product_id := _text(raw_id)) and product_id not in ordered_ids:
                ordered_ids.append(product_id)
    return [
        {
            "productId": product_id,
            "title": _text(existing.get(product_id, {}).get("title"))
            or titles.get(product_id),
            "coverImageUrl": _text(
                existing.get(product_id, {}).get("coverImageUrl")
                or existing.get(product_id, {}).get("imageUrl")
            )
            or images.get(product_id),
        }
        for product_id in ordered_ids
    ]


def _product_ids(items: Iterable[Mapping[str, object]]) -> set[str]:
    result: set[str] = set()
    for item in items:
        raw_ids = item.get("promotedProductIds")
        if isinstance(raw_ids, list):
            result.update(value for raw in raw_ids if (value := _text(raw)))
        raw_products = item.get("promotedProducts")
        if isinstance(raw_products, list):
            for product in raw_products:
                if isinstance(product, Mapping) and (
                    value := _text(product.get("productId") or product.get("id"))
                ):
                    result.add(value)
    return result


def _normalize_username(value: object) -> str | None:
    parsed = _text(value)
    return parsed.lstrip("@").casefold() if parsed else None


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    parsed = str(value).strip()
    return parsed or None
