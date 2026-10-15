from uuid import UUID

from backend.app.services.tiktok_affiliate_video_capture import (
    TikTokAffiliateVideoCaptureSession,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_video_cover_storage import (
    configured_video_cover_writer,
)
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository
from erp_api.services.video_performance_repository import VideoPerformanceRepository


def build_affiliate_video_capture(
    tenant_id: UUID,
    database: Database,
    *,
    expected_query: AffiliateCenterQuery | None = None,
    intent_job_id: str | None = None,
) -> TikTokAffiliateVideoCaptureSession:
    sync_repository = AnalyticsSyncRepository.for_affiliate_center(database)
    persistence = AffiliateVideoPersistence(
        AnalyticsRepository(database),
        VideoPerformanceRepository(database),
        cover_storage=configured_video_cover_writer(),
    )
    return TikTokAffiliateVideoCaptureSession(
        tenant_id,
        AffiliateCenterReadRepository(database),
        sync_repository,
        persistence,
        expected_query=expected_query,
        intent_job_id=intent_job_id,
    )
