from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import Numeric, case, cast, func, select

from erp_api.models.affiliate_creator import AffiliateCreatorMetric
from erp_api.models.analytics_snapshot import TikTokVideoContent
from erp_api.models.video_performance_snapshot import TikTokVideoPerformanceSnapshot

CREATOR_SUMMARY_FIELDS = {
    "affiliateGmvMinor": AffiliateCreatorMetric.affiliate_gmv_minor,
    "estimatedCommissionMinor": AffiliateCreatorMetric.estimated_commission_minor,
    "itemsSold": AffiliateCreatorMetric.items_sold,
    "affiliateOrderCount": AffiliateCreatorMetric.affiliate_order_count,
    "productImpressions": AffiliateCreatorMetric.product_impressions,
}
VIDEO_SUMMARY_FIELDS = (
    "gmvMinor",
    "orderCount",
    "itemsSold",
    "views",
    "productImpressions",
)


def empty_creator_summary() -> dict[str, int]:
    return {
        "creatorCount": 0,
        **{field: 0 for field in CREATOR_SUMMARY_FIELDS},
    }


def empty_video_summary() -> dict[str, int]:
    return {
        "videoCount": 0,
        **{field: 0 for field in VIDEO_SUMMARY_FIELDS},
    }


def creator_summary_statement(tenant_id: UUID, shop_id: UUID, report_id: UUID):
    conditions = (
        AffiliateCreatorMetric.tenant_id == tenant_id,
        AffiliateCreatorMetric.shop_id == shop_id,
        AffiliateCreatorMetric.report_id == report_id,
    )
    return select(
        func.count().label("creator_count"),
        *(
            func.sum(column).label(field)
            for field, column in CREATOR_SUMMARY_FIELDS.items()
        ),
    ).where(*conditions)


def creator_summary_from_row(row) -> dict[str, int]:
    return {
        "creatorCount": int(row.creator_count or 0),
        **{field: int(getattr(row, field) or 0) for field in CREATOR_SUMMARY_FIELDS},
    }


def video_summary_statement(
    tenant_id: UUID,
    shop_id: UUID,
    run_id: UUID,
    creator_open_id: str | None,
):
    snapshot = TikTokVideoPerformanceSnapshot
    content = TikTokVideoContent
    conditions = [
        snapshot.tenant_id == tenant_id,
        snapshot.shop_id == shop_id,
        snapshot.sync_run_id == run_id,
    ]
    if creator_open_id:
        conditions.append(content.fields["creatorOpenId"].astext == creator_open_id)
    return (
        select(
            func.count().label("video_count"),
            *(
                func.sum(_video_metric(field)).label(field)
                for field in VIDEO_SUMMARY_FIELDS
            ),
        )
        .select_from(snapshot)
        .join(
            content,
            (content.tenant_id == snapshot.tenant_id)
            & (content.shop_id == snapshot.shop_id)
            & (content.platform_video_id == snapshot.platform_video_id),
        )
        .where(*conditions)
    )


def video_summary_from_row(row) -> dict[str, int]:
    return {
        "videoCount": int(row.video_count or 0),
        **{field: int(getattr(row, field) or 0) for field in VIDEO_SUMMARY_FIELDS},
    }


def video_summary_from_rows(rows: list[tuple[object, object]]) -> dict[str, int]:
    totals = empty_video_summary()
    totals["videoCount"] = len(rows)
    for snapshot, _content in rows:
        for field in VIDEO_SUMMARY_FIELDS:
            value = _decimal(snapshot.metrics.get(field))
            if value is not None:
                totals[field] += int(value)
    return totals


def _video_metric(field: str):
    value = TikTokVideoPerformanceSnapshot.metrics[field].astext
    return case(
        (
            value.op("~")(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$"),
            cast(value, Numeric(24, 6)),
        ),
        else_=None,
    )


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
