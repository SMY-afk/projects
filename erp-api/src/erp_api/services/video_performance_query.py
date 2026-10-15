from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Numeric, case, cast, literal, select

from erp_api.models.analytics_snapshot import TikTokVideoContent
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.scraped_data import ScrapedData
from erp_api.models.video_performance_snapshot import (
    TikTokVideoPerformanceSnapshot,
)


def video_performance_statement(
    tenant_id: UUID,
    shop_id: UUID,
    *,
    window_start: datetime,
    window_end: datetime,
    currency: str,
    account_type: str,
    limit: int,
    sort_by: Literal["gmv", "gpm", "publishedAt"],
    sort_order: Literal["asc", "desc"],
):
    snapshot = TikTokVideoPerformanceSnapshot
    latest_run_id = (
        select(snapshot.sync_run_id)
        .join(
            AnalyticsSyncRun,
            (AnalyticsSyncRun.id == snapshot.sync_run_id)
            & (AnalyticsSyncRun.tenant_id == snapshot.tenant_id),
        )
        .where(
            snapshot.tenant_id == tenant_id,
            snapshot.shop_id == shop_id,
            snapshot.window_start == window_start,
            snapshot.window_end == window_end,
            snapshot.currency == currency,
            snapshot.account_type == account_type,
            AnalyticsSyncRun.tenant_id == tenant_id,
            AnalyticsSyncRun.shop_id == shop_id,
            AnalyticsSyncRun.resource_type == "video",
            AnalyticsSyncRun.status == "succeeded",
        )
        .order_by(
            AnalyticsSyncRun.finished_at.desc().nullslast(),
            AnalyticsSyncRun.started_at.desc(),
            AnalyticsSyncRun.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    field_text = (
        TikTokVideoContent.fields["videoPostTime"].astext
        if sort_by == "publishedAt"
        else snapshot.metrics[{"gmv": "gmvAmount", "gpm": "gpmAmount"}[sort_by]].astext
    )
    sort_value = field_text
    if sort_by in {"gmv", "gpm"}:
        sort_value = case(
            (
                field_text.op("~")(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$"),
                cast(field_text, Numeric(20, 4)),
            ),
            else_=None,
        )
    ordered_value = sort_value.asc() if sort_order == "asc" else sort_value.desc()
    return (
        select(
            snapshot.platform_video_id,
            TikTokVideoContent.fields,
            snapshot.metrics,
            TikTokVideoContent.source_status,
            TikTokVideoContent.status,
            snapshot.source_updated_at,
            snapshot.captured_at,
            ScrapedData.raw_data,
        )
        .join(
            TikTokVideoContent,
            (TikTokVideoContent.tenant_id == snapshot.tenant_id)
            & (TikTokVideoContent.shop_id == snapshot.shop_id)
            & (TikTokVideoContent.platform_video_id == snapshot.platform_video_id),
        )
        .outerjoin(
            ScrapedData,
            (ScrapedData.tenant_id == tenant_id)
            & (ScrapedData.data_type == "seller_video_completion")
            & (
                ScrapedData.platform_id
                == literal("seller_video_completion:") + snapshot.platform_video_id
            ),
        )
        .where(
            snapshot.tenant_id == tenant_id,
            snapshot.shop_id == shop_id,
            snapshot.window_start == window_start,
            snapshot.window_end == window_end,
            snapshot.currency == currency,
            snapshot.account_type == account_type,
            snapshot.sync_run_id == latest_run_id,
        )
        .order_by(
            ordered_value.nullslast(),
            snapshot.source_updated_at.desc().nullslast(),
            snapshot.captured_at.desc(),
        )
        .limit(limit)
    )
