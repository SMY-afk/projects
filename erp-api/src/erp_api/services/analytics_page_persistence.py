from dataclasses import replace
from datetime import datetime
from uuid import UUID

from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.analytics_resource_types import AnalyticsContentResourceType
from erp_api.services.video_performance_fields import CONTENT_FIELD_NAMES
from erp_api.services.video_performance_repository import VideoPerformanceRepository


async def persist_analytics_page(
    analytics_repository: AnalyticsRepository,
    video_performance_repository: VideoPerformanceRepository,
    tenant_id: UUID,
    shop_id: UUID,
    run_id: UUID,
    resource_type: AnalyticsContentResourceType,
    items,
    platform_request_id: str | None,
    *,
    window_start: datetime,
    window_end: datetime,
    currency: str,
    account_type: str,
    video_external_id_field: str,
    live_external_id_field: str,
) -> int:
    if resource_type == "video":
        metadata_items = [
            replace(
                item,
                fields={
                    key: value
                    for key, value in item.fields.items()
                    if key in CONTENT_FIELD_NAMES or key == video_external_id_field
                },
            )
            for item in items
        ]
        await analytics_repository.upsert_video_contents(
            tenant_id,
            shop_id,
            metadata_items,
            external_id_field=video_external_id_field,
            platform_request_id=platform_request_id,
            preserve_existing_details=True,
        )
        return await video_performance_repository.upsert_page(
            tenant_id,
            shop_id,
            run_id,
            items,
            window_start=window_start,
            window_end=window_end,
            currency=currency,
            account_type=account_type,
            external_id_field=video_external_id_field,
            platform_request_id=platform_request_id,
        )
    return await analytics_repository.upsert_live_sessions(
        tenant_id,
        shop_id,
        items,
        external_id_field=live_external_id_field,
        platform_request_id=platform_request_id,
    )
