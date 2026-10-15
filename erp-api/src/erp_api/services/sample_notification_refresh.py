from __future__ import annotations

from types import SimpleNamespace

from erp_api.services.sample_notification_products import (
    list_notification_product_image_urls,
)


async def load_refresh_product_images(database, targets) -> None:
    async with database.system_session_factory() as session:
        for target in targets:
            application = target.application
            target.product_image_urls = await list_notification_product_image_urls(
                session,
                tenant_id=application.tenant_id,
                shop_id=application.shop_id,
                application_id=application.id,
                platform_status=application.platform_status,
                creator_open_id=application.creator_open_id,
                creator_username=application.creator_username,
                fallback_image_url=application.sku_image_url,
                stored_image_urls=tuple(application.product_image_urls or ()),
                sample_type=application.sample_type or "free",
            )


def build_refresh_card_task(target):
    application = target.application
    return SimpleNamespace(
        payload=target.outbox.payload,
        sample_type=application.sample_type or "free",
        creator_name=(
            application.creator_nickname
            or application.creator_username
            or application.creator_open_id
            or "未知达人"
        ),
        creator_username=application.creator_username,
        creator_level=application.creator_level,
        follower_count=application.follower_count,
        creator_gmv_minor=application.creator_gmv_minor,
        creator_gmv_currency=application.creator_gmv_currency,
        creator_units_sold=application.creator_units_sold,
        creator_ec_video_view=application.creator_ec_video_view,
        creator_content_count=application.creator_content_count,
        creator_fulfillment_percentage=application.creator_fulfillment_percentage,
        creator_pps=application.creator_pps,
        creator_rating=application.creator_rating,
        creator_avatar_object_key=application.creator_avatar_object_key,
        creator_profile_snapshot=application.creator_profile_snapshot,
        creator_profile_observed_at=application.creator_profile_observed_at,
        product_name=(
            application.product_title
            or application.sku_name
            or application.product_id
            or "未知商品"
        ),
        product_image_urls=target.product_image_urls,
        shop_name=target.shop.shop_name,
        platform_status=application.platform_status,
        approve_expiration_at=application.approve_expiration_at,
        source_observed_at=application.source_observed_at,
        feishu_record_id=target.workflow.feishu_record_id,
    )
