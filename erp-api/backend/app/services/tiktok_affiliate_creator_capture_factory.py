from collections.abc import Collection
from uuid import UUID

from backend.app.services.tiktok_affiliate_creator_capture import (
    TikTokAffiliateCreatorCaptureSession,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_persistence import AffiliateCreatorPersistence
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


def build_affiliate_creator_capture(
    tenant_id: UUID,
    database: Database,
    *,
    approved_filter_fields: Collection[str] = (),
    expected_query: AffiliateCenterQuery | None = None,
    intent_job_id: str | None = None,
) -> TikTokAffiliateCreatorCaptureSession:
    sync_repository = AnalyticsSyncRepository.for_affiliate_center(database)
    return TikTokAffiliateCreatorCaptureSession(
        tenant_id,
        AffiliateCenterReadRepository(database),
        sync_repository,
        AffiliateCreatorPersistence(database),
        approved_filter_fields=approved_filter_fields,
        expected_query=expected_query,
        intent_job_id=intent_job_id,
    )
