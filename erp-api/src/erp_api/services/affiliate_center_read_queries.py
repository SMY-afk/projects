from typing import Literal

from sqlalchemy import Numeric, case, cast, desc, select

from erp_api.models.affiliate_creator import AffiliateCreator, AffiliateCreatorMetric
from erp_api.models.analytics_sync import AnalyticsSyncRun

SortOrder = Literal["asc", "desc"]
CreatorSort = Literal[
    "username",
    "affiliateGmvMinor",
    "estimatedCommissionMinor",
    "affiliateOrderCount",
    "itemsSold",
    "productImpressions",
    "clickThroughRate",
    "affiliateVideoCount",
    "affiliateFollowerCount",
]
VideoSort = Literal[
    "gmvMinor",
    "estimatedCommissionMinor",
    "orderCount",
    "itemsSold",
    "productImpressions",
    "views",
    "videoPostTime",
]

CREATOR_SORTS = {
    "username": AffiliateCreator.username,
    "affiliateGmvMinor": AffiliateCreatorMetric.affiliate_gmv_minor,
    "estimatedCommissionMinor": AffiliateCreatorMetric.estimated_commission_minor,
    "affiliateOrderCount": AffiliateCreatorMetric.affiliate_order_count,
    "itemsSold": AffiliateCreatorMetric.items_sold,
    "productImpressions": AffiliateCreatorMetric.product_impressions,
    "clickThroughRate": AffiliateCreatorMetric.click_through_rate,
    "affiliateVideoCount": AffiliateCreatorMetric.affiliate_video_count,
    "affiliateFollowerCount": AffiliateCreatorMetric.affiliate_follower_count,
}
VIDEO_SORTS = {
    "gmvMinor": "gmvMinor",
    "estimatedCommissionMinor": "estimatedCommissionMinor",
    "orderCount": "orderCount",
    "itemsSold": "itemsSold",
    "productImpressions": "productImpressions",
    "views": "views",
    "videoPostTime": "videoPostTime",
}


def complete_video_run(tenant_id, query, window_start, window_end):
    return (
        select(AnalyticsSyncRun)
        .where(
            AnalyticsSyncRun.tenant_id == tenant_id,
            AnalyticsSyncRun.shop_id == query.shop_id,
            AnalyticsSyncRun.resource_type == "affiliate_video",
            AnalyticsSyncRun.window_start == window_start,
            AnalyticsSyncRun.window_end == window_end,
            AnalyticsSyncRun.currency == query.currency,
            AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
            AnalyticsSyncRun.status == "succeeded",
        )
        .order_by(
            desc(AnalyticsSyncRun.finished_at),
            desc(AnalyticsSyncRun.started_at),
        )
        .limit(1)
    )


def latest_run(
    tenant_id,
    shop_id,
    resource_type,
    *,
    succeeded=False,
    account_type=None,
):
    conditions = [
        AnalyticsSyncRun.tenant_id == tenant_id,
        AnalyticsSyncRun.shop_id == shop_id,
        AnalyticsSyncRun.resource_type.in_(resource_type)
        if isinstance(resource_type, tuple)
        else AnalyticsSyncRun.resource_type == resource_type,
    ]
    if succeeded:
        conditions.append(AnalyticsSyncRun.status == "succeeded")
    if account_type:
        conditions.append(AnalyticsSyncRun.account_type == account_type)
    return (
        select(AnalyticsSyncRun)
        .where(*conditions)
        .order_by(desc(AnalyticsSyncRun.started_at), desc(AnalyticsSyncRun.id))
        .limit(1)
    )


def latest_failure_run(tenant_id, shop_id, resource_type, *, account_type=None):
    conditions = [
        AnalyticsSyncRun.tenant_id == tenant_id,
        AnalyticsSyncRun.shop_id == shop_id,
        AnalyticsSyncRun.resource_type.in_(resource_type)
        if isinstance(resource_type, tuple)
        else AnalyticsSyncRun.resource_type == resource_type,
        AnalyticsSyncRun.status.in_(("partial", "failed", "dead_letter")),
    ]
    if account_type:
        conditions.append(AnalyticsSyncRun.account_type == account_type)
    return (
        select(AnalyticsSyncRun)
        .where(*conditions)
        .order_by(desc(AnalyticsSyncRun.started_at), desc(AnalyticsSyncRun.id))
        .limit(1)
    )


def video_sort_value(snapshot, content, sort):
    source = content.fields if sort == "videoPostTime" else snapshot.metrics
    value = source[VIDEO_SORTS[sort]].astext
    if sort == "videoPostTime":
        return value
    return case(
        (value.op("~")(r"^-?(?:\d+(?:\.\d*)?|\.\d+)$"), cast(value, Numeric(24, 6))),
        else_=None,
    )
