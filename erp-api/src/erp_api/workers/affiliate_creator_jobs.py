from datetime import timedelta
from uuid import UUID

from erp_api.core.config import get_settings
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_creator_schedule import (
    AffiliateCreatorScheduleService,
)
from erp_api.workers.analytics_jobs import _now


async def enqueue_scheduled_affiliate_creator_syncs(ctx) -> int:
    settings = get_settings()
    health_repository = AffiliateCaptureHealthRepository(ctx["redis"])

    async def latest_available(tenant_id: UUID, shop_id: UUID, resource):
        health = await health_repository.get(tenant_id, shop_id)
        if health.state != "online" or not health.session_available:
            return None
        return await health_repository.observed_date_for(
            tenant_id, shop_id, resource.value
        )

    async def recovered_at(tenant_id: UUID, shop_id: UUID):
        return (await health_repository.get(tenant_id, shop_id)).recovered_at

    service = AffiliateCreatorScheduleService(
        ctx["database"],
        max_attempts=settings.tiktok_affiliate_creator_schedule_max_attempts,
        retry_delay=timedelta(minutes=settings.tiktok_affiliate_creator_retry_minutes),
        recovery_provider=recovered_at,
        availability_provider=latest_available,
    )
    return await service.enqueue_due(_now(ctx))
