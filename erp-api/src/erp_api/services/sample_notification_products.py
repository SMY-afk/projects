from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select

from erp_api.models.sample_application import SampleApplication


async def list_notification_product_image_urls(
    session,
    *,
    tenant_id: UUID,
    shop_id: UUID,
    application_id: UUID,
    platform_status: str,
    creator_open_id: str | None,
    creator_username: str | None,
    fallback_image_url: str | None,
    stored_image_urls: tuple[str, ...] = (),
    sample_type: str = "free",
) -> tuple[str, ...]:
    """List real product images for the same current creator application set."""
    stored = _deduplicate(stored_image_urls)
    if stored:
        return stored
    open_id = _clean(creator_open_id)
    username = _clean(creator_username)
    fallback = _deduplicate((fallback_image_url,))
    if open_id is None or username is None:
        return fallback

    statement = (
        select(SampleApplication.sku_image_url)
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.sample_type == sample_type,
            SampleApplication.platform_status == platform_status,
            SampleApplication.creator_open_id == open_id,
            func.lower(func.trim(SampleApplication.creator_username))
            == username.casefold(),
            SampleApplication.sku_image_url.is_not(None),
        )
        .order_by(
            case((SampleApplication.id == application_id, 0), else_=1),
            SampleApplication.created_at,
            SampleApplication.platform_application_id,
        )
    )
    rows = (await session.execute(statement)).all()
    urls = _deduplicate(url for (url,) in rows)
    return urls or fallback


def _clean(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _deduplicate(values) -> tuple[str, ...]:
    result = []
    seen = set()
    for value in values:
        cleaned = _clean(value)
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return tuple(result)
