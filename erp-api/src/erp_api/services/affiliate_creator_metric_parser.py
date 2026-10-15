from __future__ import annotations

from collections.abc import Iterable, Mapping
from hashlib import sha256

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    require_affiliate_payload,
)
from erp_api.services.affiliate_metric_parse_support import (
    count,
    creator_username_key,
    currency_code,
    image_url,
    major_money_minor,
    minor_money,
    nonnegative_decimal,
    rate,
    text,
)
from erp_api.services.affiliate_metric_source_contract import (
    extensions,
    query_context,
    source_identifiers,
)
from erp_api.services.affiliate_metric_source_fields import (
    CREATOR_CANONICAL_FIELDS,
    CREATOR_PAGE_FIELDS,
)


class AffiliateCreatorMetricParseError(ValueError):
    pass


def parse_creator_page_payload(
    payload: object, *, query: AffiliateCenterQuery
) -> list[AffiliateCreatorMetricDTO]:
    try:
        require_affiliate_payload("creators", payload)
        if not isinstance(payload, Mapping):
            raise TypeError("payload: expected an object")
        data = payload["data"]
        if not isinstance(data, Mapping):
            raise TypeError("payload.data: expected an object")
        context = query_context(query, AffiliateCenterResource.CREATORS)
        result: list[AffiliateCreatorMetricDTO] = []
        for segment in data["segments"]:
            for timed_list in segment["timed_lists"]:
                for stat in timed_list["stats"]:
                    result.append(_parse_page_stat(stat, query, context))
        return result
    except (
        AffiliatePayloadDiscriminatorError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AffiliateCreatorMetricParseError):
            raise
        raise AffiliateCreatorMetricParseError(str(error)) from error


def parse_creator_official_rows(
    rows: Iterable[Mapping[str, object]], *, query: AffiliateCenterQuery
) -> list[AffiliateCreatorMetricDTO]:
    context = query_context(query, AffiliateCenterResource.CREATORS)
    return [_parse_canonical_row(row, query, context) for row in rows]


def _parse_page_stat(
    stat: Mapping[str, object],
    query: AffiliateCenterQuery,
    context: Mapping[str, object],
) -> AffiliateCreatorMetricDTO:
    affiliate_gmv, _ = major_money_minor(
        stat.get("revenue"), query.currency, "affiliateGmv"
    )
    private_id = text(stat.get("id"), "creatorId", required=True) or ""
    username = text(stat.get("handle"), "username")
    anonymous = username is None
    if anonymous:
        digest = sha256(private_id.encode("utf-8")).hexdigest()[:16]
        username = f"@unknown_{digest}"
    extra_fields = extensions(stat, CREATOR_PAGE_FIELDS)
    if anonymous:
        extra_fields["identity"] = {"usernameMissing": True}
    return AffiliateCreatorMetricDTO(
        username=username,
        username_normalized=creator_username_key(username),
        avatar_url=image_url(stat.get("avatar"), "avatarUrl"),
        **context,
        source_identifiers=source_identifiers(tiktok_page_creator_id=private_id),
        affiliate_gmv_minor=affiliate_gmv,
        affiliate_live_gmv_minor=_page_money(
            stat, "live_revenue", query.currency, "affiliateLiveGmv"
        ),
        affiliate_video_gmv_minor=_page_money(
            stat, "video_revenue", query.currency, "affiliateVideoGmv"
        ),
        affiliate_showcase_gmv_minor=_page_money(
            stat, "product_card_revenue", query.currency, "affiliateShowcaseGmv"
        ),
        affiliate_product_items_sold=count(
            stat.get("product_sold"),
            "affiliateProductItemsSold",
        ),
        items_sold=count(stat.get("item_sold"), "itemsSold"),
        estimated_commission_minor=_page_money(
            stat, "est_commission", query.currency, "estimatedCommission"
        ),
        average_order_amount_minor=_page_money(
            stat, "aov", query.currency, "averageOrderAmount"
        ),
        showcase_product_count=count(stat.get("product_cnt"), "showcaseProductCount"),
        affiliate_order_count=count(stat.get("order_cnt"), "affiliateOrderCount"),
        click_through_rate=rate(
            stat.get("ctr"), "clickThroughRate", allow_above_one=True
        ),
        product_impressions=count(stat.get("product_impression"), "productImpressions"),
        average_affiliate_customers=nonnegative_decimal(
            stat.get("buyer_cnt_daily_avg"), "averageAffiliateCustomers"
        ),
        affiliate_live_count=count(stat.get("live_cnt"), "affiliateLiveCount"),
        affiliate_video_count=count(stat.get("video_cnt"), "affiliateVideoCount"),
        target_collaboration_gmv_minor=_page_money(
            stat,
            "target_collaboration_revenue",
            query.currency,
            "targetCollaborationGmv",
        ),
        target_collaboration_estimated_commission_minor=_page_money(
            stat,
            "target_collaboration_est_commission",
            query.currency,
            "targetCollaborationEstimatedCommission",
        ),
        open_collaboration_gmv_minor=_page_money(
            stat,
            "open_collaboration_revenue",
            query.currency,
            "openCollaborationGmv",
        ),
        open_collaboration_estimated_commission_minor=_page_money(
            stat,
            "open_collaboration_est_commission",
            query.currency,
            "openCollaborationEstimatedCommission",
        ),
        refunded_affiliate_gmv_minor=_page_money(
            stat,
            "refund_revenue",
            query.currency,
            "refundedAffiliateGmv",
        ),
        refunded_affiliate_product_count=count(
            stat.get("refund_item_sold"),
            "refundedAffiliateProductCount",
        ),
        affiliate_follower_count=count(
            stat.get("follow_cnt"), "affiliateFollowerCount"
        ),
        extensions=extra_fields,
    )


def _parse_canonical_row(
    row: Mapping[str, object],
    query: AffiliateCenterQuery,
    context: Mapping[str, object],
) -> AffiliateCreatorMetricDTO:
    try:
        username = (
            text(
                row.get("username"),
                "username",
                required=True,
            )
            or ""
        )
        currency_code(row.get("currency"), query.currency)
        return AffiliateCreatorMetricDTO(
            creator_open_id=text(row.get("creatorOpenId"), "creatorOpenId"),
            source_identifiers=source_identifiers(
                official_creator_id=text(row.get("creatorId"), "creatorId")
            ),
            username=username,
            username_normalized=creator_username_key(username),
            avatar_url=image_url(row.get("avatarUrl"), "avatarUrl"),
            **context,
            **_canonical_metrics(row),
            extensions=extensions(row, CREATOR_CANONICAL_FIELDS),
        )
    except (TypeError, ValueError) as error:
        raise AffiliateCreatorMetricParseError(str(error)) from error


def _canonical_metrics(row: Mapping[str, object]) -> dict[str, object]:
    money = lambda name: minor_money(row.get(name), name)
    integer = lambda name: count(row.get(name), name)
    return {
        "affiliate_gmv_minor": money("affiliateGmvMinor"),
        "affiliate_live_gmv_minor": money("affiliateLiveGmvMinor"),
        "affiliate_video_gmv_minor": money("affiliateVideoGmvMinor"),
        "affiliate_showcase_gmv_minor": money("affiliateShowcaseGmvMinor"),
        "affiliate_product_items_sold": integer("affiliateProductItemsSold"),
        "items_sold": integer("itemsSold"),
        "estimated_commission_minor": money("estimatedCommissionMinor"),
        "estimated_flat_fee_minor": money("estimatedFlatFeeMinor"),
        "average_order_amount_minor": money("averageOrderAmountMinor"),
        "showcase_product_count": integer("showcaseProductCount"),
        "affiliate_order_count": integer("affiliateOrderCount"),
        "click_through_rate": rate(
            row.get("clickThroughRate"),
            "clickThroughRate",
            allow_above_one=True,
        ),
        "product_impressions": integer("productImpressions"),
        "average_affiliate_customers": nonnegative_decimal(
            row.get("averageAffiliateCustomers"), "averageAffiliateCustomers"
        ),
        "affiliate_live_count": integer("affiliateLiveCount"),
        "affiliate_video_count": integer("affiliateVideoCount"),
        "target_collaboration_gmv_minor": money("targetCollaborationGmvMinor"),
        "target_collaboration_estimated_commission_minor": money(
            "targetCollaborationEstimatedCommissionMinor"
        ),
        "open_collaboration_gmv_minor": money("openCollaborationGmvMinor"),
        "open_collaboration_estimated_commission_minor": money(
            "openCollaborationEstimatedCommissionMinor"
        ),
        "refunded_affiliate_gmv_minor": money("refundedAffiliateGmvMinor"),
        "refunded_affiliate_product_count": integer("refundedAffiliateProductCount"),
        "affiliate_follower_count": integer("affiliateFollowerCount"),
    }


def _page_money(
    row: Mapping[str, object], name: str, currency: str, field: str
) -> int | None:
    value = row.get(name)
    if value is None:
        return None
    return major_money_minor(value, currency, field)[0]
