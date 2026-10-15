from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.models.affiliate_creator_detail import (
    AffiliateCreatorDetailItem,
    AffiliateCreatorDetailReport,
)
from erp_api.models.analytics_snapshot import TikTokVideoContent
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.video_performance_snapshot import TikTokVideoPerformanceSnapshot

CREATOR_USERNAME = "@e2e_affiliate_creator"
WINDOW_START = date(2026, 8, 23)
WINDOW_END = date(2026, 8, 29)
WINDOW_START_UTC = datetime(2026, 8, 23, 7, tzinfo=UTC)
WINDOW_END_UTC = datetime(2026, 8, 30, 7, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 30, 9, tzinfo=UTC)


def affiliate_rows(
    *, scenario_id: UUID, tenant_id: UUID, shop_id: UUID
) -> tuple[UUID, list[list[object]]]:
    creator_id = uuid4()
    creator_report_id = uuid4()
    video_run_id = uuid4()
    detail_run_id = uuid4()
    detail_report_id = uuid4()
    query_fingerprint = sha256(f"{scenario_id}:creator-query".encode()).hexdigest()
    rows: list[object] = [
        AffiliateCreator(
            id=creator_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            username=CREATOR_USERNAME,
            username_normalized=CREATOR_USERNAME,
            creator_open_id="e2e-affiliate-open-id",
            source_identifiers={"fixture": True},
            extensions={},
            first_seen_at=CAPTURED_AT,
            last_seen_at=CAPTURED_AT,
        ),
        AffiliateCreatorReport(
            id=creator_report_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            scope_label="E2E Affiliate Center",
            period_start=WINDOW_START,
            period_end=WINDOW_END,
            window_start_utc=WINDOW_START_UTC,
            window_end_utc=WINDOW_END_UTC,
            shop_timezone="America/Los_Angeles",
            currency="USD",
            source_kind="browser_capture",
            source_fingerprint=f"e2e-{scenario_id.hex}",
            source_metadata={"fixture": True},
            query_fingerprint=query_fingerprint,
            revision_no=1,
            status="complete",
            expected_total=1,
            pages_fetched=1,
            records_received=1,
            records_unique=1,
            duplicate_count=0,
            filters={},
            captured_at=CAPTURED_AT,
        ),
        AffiliateCreatorMetric(
            tenant_id=tenant_id,
            shop_id=shop_id,
            report_id=creator_report_id,
            creator_id=creator_id,
            affiliate_gmv_minor=12345,
            estimated_commission_minor=1234,
            items_sold=12,
            affiliate_order_count=8,
            average_affiliate_customers=Decimal("7"),
            click_through_rate="0.125",
            product_impressions=800,
            affiliate_video_count=3,
            extensions={},
        ),
        AnalyticsSyncRun(
            id=video_run_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            resource_type="affiliate_video",
            job_id=f"e2e-affiliate-video-{scenario_id.hex}",
            status="succeeded",
            attempt_count=1,
            window_start=WINDOW_START_UTC,
            window_end=WINDOW_END_UTC,
            currency="USD",
            account_type="AFFILIATE_ACCOUNTS",
            latest_available_date=WINDOW_END,
            fetched_count=1,
            persisted_count=1,
            last_source_updated_at=CAPTURED_AT,
            started_at=CAPTURED_AT,
            finished_at=CAPTURED_AT,
        ),
        TikTokVideoContent(
            tenant_id=tenant_id,
            shop_id=shop_id,
            platform_video_id="e2e-affiliate-video",
            fields={
                "title": "E2E Affiliate Video",
                "creatorOpenId": "e2e-affiliate-open-id",
                "creatorUsername": CREATOR_USERNAME,
                "creatorNickname": "E2E Affiliate Creator",
                "videoPostTime": "2026-08-25T12:00:00Z",
            },
            source_status="active",
            status="active",
            source_updated_at=CAPTURED_AT,
            observed_at=CAPTURED_AT,
        ),
        TikTokVideoPerformanceSnapshot(
            tenant_id=tenant_id,
            shop_id=shop_id,
            sync_run_id=video_run_id,
            platform_video_id="e2e-affiliate-video",
            window_start=WINDOW_START_UTC,
            window_end=WINDOW_END_UTC,
            currency="USD",
            account_type="AFFILIATE_ACCOUNTS",
            metrics={
                "gmvMinor": 5432,
                "estimatedCommissionMinor": 543,
                "orderCount": 4,
                "itemsSold": 6,
                "productImpressions": 400,
                "productClicks": 50,
                "views": 1000,
                "productClickThroughRate": "0.125",
            },
            source_updated_at=CAPTURED_AT,
            captured_at=CAPTURED_AT,
        ),
        AnalyticsSyncRun(
            id=detail_run_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            resource_type="affiliate_creator_detail",
            job_id=f"e2e-affiliate-detail-{scenario_id.hex}",
            status="succeeded",
            attempt_count=1,
            window_start=WINDOW_START_UTC,
            window_end=WINDOW_END_UTC,
            currency="USD",
            account_type="AFFILIATE_ACCOUNTS",
            fetched_count=1,
            persisted_count=1,
            started_at=CAPTURED_AT,
            finished_at=CAPTURED_AT,
        ),
        AffiliateCreatorDetailReport(
            id=detail_report_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            creator_id=creator_id,
            sync_run_id=detail_run_id,
            resource_kind="video",
            query_fingerprint=sha256(
                f"{scenario_id}:creator-detail-query".encode()
            ).hexdigest(),
            revision_no=1,
            window_start_utc=WINDOW_START_UTC,
            window_end_utc=WINDOW_END_UTC,
            shop_timezone="America/Los_Angeles",
            currency="USD",
            filters={},
            status="complete",
            expected_total=1,
            pages_fetched=1,
            records_received=1,
            records_unique=1,
            captured_at=CAPTURED_AT,
            finished_at=CAPTURED_AT,
        ),
        AffiliateCreatorDetailItem(
            tenant_id=tenant_id,
            shop_id=shop_id,
            report_id=detail_report_id,
            platform_content_id="e2e-affiliate-detail-video",
            identity={
                "title": "E2E Creator Detail Video",
                "publishedAt": "2026-08-25T12:00:00Z",
            },
            metrics={
                "views": 1000,
                "gmvMinor": 5432,
                "orderCount": 4,
                "itemsSold": 6,
                "productClickThroughRate": "0.125",
            },
            extensions={},
            captured_at=CAPTURED_AT,
        ),
    ]
    return creator_id, [
        [rows[0], rows[1], rows[3], rows[4], rows[6]],
        [rows[2], rows[5], rows[7]],
        [rows[8]],
    ]
