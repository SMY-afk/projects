from __future__ import annotations

from collections.abc import Mapping

from erp_api.services.affiliate_metric_parse_support import count, minor_money, rate


def parse_canonical_video_metrics(row: Mapping[str, object]) -> dict[str, object]:
    def money(name: str) -> int | None:
        return minor_money(row.get(name), name)

    def integer(name: str) -> int | None:
        return count(row.get(name), name)

    return {
        "gmv_minor": money("gmvMinor"),
        "estimated_commission_minor": money("estimatedCommissionMinor"),
        "average_order_value_minor": money("averageOrderValueMinor"),
        "average_gmv_per_buyer_minor": money("averageGmvPerBuyerMinor"),
        "refunded_gmv_minor": money("refundedGmvMinor"),
        "distinct_gpm_minor": money("distinctGpmMinor"),
        "order_count": integer("orderCount"),
        "items_sold": integer("itemsSold"),
        "refunded_items": integer("refundedItems"),
        "product_impressions": integer("productImpressions"),
        "product_clicks": integer("productClicks"),
        "views": integer("views"),
        "likes": integer("likes"),
        "comments": integer("comments"),
        "shares": integer("shares"),
        "product_click_through_rate": rate(
            row.get("productClickThroughRate"),
            "productClickThroughRate",
            allow_above_one=True,
        ),
        "engagement_rate": rate(
            row.get("engagementRate"), "engagementRate", allow_above_one=True
        ),
        "finish_rate": rate(row.get("finishRate"), "finishRate", allow_above_one=True),
    }
