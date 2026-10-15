from __future__ import annotations

from erp_api.services.sample_notification_avatar import (
    SampleNotificationAvatarError,
)
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageError,
)


async def resolve_notification_image_keys(
    avatar_service,
    product_service,
    *,
    avatar_object_key: str | None,
    product_image_urls: tuple[str, ...],
) -> tuple[str | None, tuple[str, ...]]:
    avatar_img_key = None
    product_img_keys = []
    if avatar_service is not None and avatar_object_key:
        try:
            avatar_img_key = await avatar_service.resolve_img_key(avatar_object_key)
        except (SampleNotificationAvatarError, ValueError):
            pass
    if product_service is not None:
        for product_image_url in product_image_urls:
            try:
                product_img_keys.append(
                    await product_service.resolve_img_key(product_image_url)
                )
            except (SampleNotificationProductImageError, ValueError):
                continue
    return avatar_img_key, tuple(product_img_keys)
