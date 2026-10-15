from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_creator_schedule import (
    AffiliateScheduleService,
    RecoveryProvider,
    ScheduleEnqueuer,
)
from erp_api.services.affiliate_schedule_coordination import AvailabilityProvider
from erp_api.services.affiliate_schedule_queries import (
    ScheduledShop,
    scheduled_affiliate_query,
    scheduled_resource_job_base,
)


class AffiliateVideoScheduleService(AffiliateScheduleService):
    def __init__(
        self,
        database,
        *,
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(minutes=10),
        enqueuer: ScheduleEnqueuer | None = None,
        recovery_provider: RecoveryProvider | None = None,
        availability_provider: AvailabilityProvider | None = None,
    ) -> None:
        super().__init__(
            database,
            resource=AffiliateCenterResource.VIDEOS,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            enqueuer=enqueuer,
            recovery_provider=recovery_provider,
            availability_provider=availability_provider,
        )


def scheduled_video_query(
    shop: ScheduledShop, latest_available: date
) -> AffiliateCenterQuery:
    return scheduled_affiliate_query(
        shop, latest_available, AffiliateCenterResource.VIDEOS
    )


def scheduled_video_job_base(schedule_date: date, shop_id: UUID) -> str:
    return scheduled_resource_job_base(
        schedule_date, shop_id, AffiliateCenterResource.VIDEOS
    )
