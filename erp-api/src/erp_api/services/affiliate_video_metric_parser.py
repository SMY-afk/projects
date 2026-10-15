from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoMetricDTO
from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    require_affiliate_payload,
)
from erp_api.services.affiliate_metric_parse_support import (
    count,
    currency_code,
    image_url,
    major_money_minor,
    nonnegative_decimal,
    rate,
    string_tuple,
    text,
    timestamp,
)
from erp_api.services.affiliate_metric_source_contract import (
    extensions,
    grouped_extensions,
    query_context,
    source_identifiers,
)
from erp_api.services.affiliate_metric_source_fields import (
    VIDEO_CANONICAL_FIELDS,
    VIDEO_CREATOR_FIELDS,
    VIDEO_INFO_FIELDS,
    VIDEO_METRIC_FIELDS,
    VIDEO_PERFORMANCE_FIELDS,
    VIDEO_PLAY_FIELDS,
)
from erp_api.services.affiliate_video_canonical_metrics import (
    parse_canonical_video_metrics,
)
from erp_api.services.affiliate_video_content_parser import (
    first_play_url,
    parse_canonical_products,
    parse_page_products,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


class AffiliateVideoMetricParseError(ValueError):
    pass


def parse_video_page_payload(
    payload: object, *, query: AffiliateCenterQuery
) -> list[AffiliateVideoMetricDTO]:
    try:
        require_affiliate_payload("videos", payload)
        if not isinstance(payload, Mapping):
            raise TypeError("payload: expected an object")
        data = payload["data"]
        if not isinstance(data, Mapping):
            raise TypeError("payload.data: expected an object")
        context = query_context(query, AffiliateCenterResource.VIDEOS)
        result: list[AffiliateVideoMetricDTO] = []
        for segment in data["video_list_segments_v2"]:
            for performance in segment.get("video_performances", []):
                result.append(_parse_page_performance(performance, query, context))
        return result
    except (
        AffiliatePayloadDiscriminatorError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AffiliateVideoMetricParseError):
            raise
        raise AffiliateVideoMetricParseError(str(error)) from error


def parse_video_official_items(
    items: Iterable[TikTokAnalyticsItem], *, query: AffiliateCenterQuery
) -> list[AffiliateVideoMetricDTO]:
    context = query_context(query, AffiliateCenterResource.VIDEOS)
    return [
        _parse_canonical_row(
            item.fields,
            query,
            context,
            status=item.status,
            source_updated_at=item.source_updated_at,
        )
        for item in items
    ]


def parse_video_export_rows(
    rows: Iterable[Mapping[str, object]], *, query: AffiliateCenterQuery
) -> list[AffiliateVideoMetricDTO]:
    context = query_context(query, AffiliateCenterResource.VIDEOS)
    return [_parse_canonical_row(row, query, context) for row in rows]


def _parse_page_performance(
    performance: Mapping[str, object],
    query: AffiliateCenterQuery,
    context: Mapping[str, object],
) -> AffiliateVideoMetricDTO:
    creator = _mapping(performance.get("creator_base"), "creator_base")
    video = _mapping(performance.get("video_info"), "video_info")
    metrics = _mapping(performance.get("video_metrics"), "video_metrics")
    play_info = (
        _mapping(video["play_info"], "video_info.play_info")
        if video.get("play_info") is not None
        else {}
    )
    gmv, _ = major_money_minor(metrics.get("video_gmv"), query.currency, "gmv")
    return AffiliateVideoMetricDTO(
        video_id=text(video.get("item_id"), "videoId", required=True) or "",
        **context,
        source_identifiers=source_identifiers(
            tiktok_page_creator_id=text(creator.get("oec_id"), "creatorId")
        ),
        creator_username=text(creator.get("handle_name"), "creatorUsername"),
        creator_nickname=text(creator.get("nick_name"), "creatorNickname"),
        creator_avatar_url=image_url(creator.get("avatar"), "creatorAvatarUrl"),
        creator_follower_count=count(
            creator.get("follower_cnt"), "creatorFollowerCount"
        ),
        title=text(video.get("title"), "title"),
        video_post_time=timestamp(video.get("create_time"), "videoPostTime"),
        duration_seconds=nonnegative_decimal(
            play_info.get("duration"), "durationSeconds"
        ),
        cover_image_url=image_url(video.get("cover"), "coverImageUrl"),
        play_url=first_play_url(play_info.get("play_urls")),
        play_id=text(play_info.get("id"), "playId"),
        width=count(play_info.get("width"), "width"),
        height=count(play_info.get("height"), "height"),
        promoted_product_ids=string_tuple(
            performance.get("product_ids"), "promotedProductIds"
        ),
        promoted_products=parse_page_products(performance.get("product_base_list")),
        gmv_minor=gmv,
        estimated_commission_minor=_page_money(
            metrics,
            "video_estimated_commission",
            query.currency,
            "estimatedCommission",
        ),
        average_order_value_minor=_page_money(
            metrics, "video_average_order_value", query.currency, "averageOrderValue"
        ),
        average_gmv_per_buyer_minor=_page_money(
            metrics,
            "video_average_gmv_per_buyer",
            query.currency,
            "averageGmvPerBuyer",
        ),
        refunded_gmv_minor=_page_money(
            metrics, "video_refunded_gmv", query.currency, "refundedGmv"
        ),
        distinct_gpm_minor=_page_money(
            metrics, "video_distinct_gpm", query.currency, "distinctGpm"
        ),
        order_count=_page_count(metrics, "orderCount", "video_orders_cnt"),
        items_sold=_page_count(metrics, "itemsSold", "video_items_sold_cnt"),
        refunded_items=_page_count(
            metrics, "refundedItems", "video_refunded_items_cnt"
        ),
        product_impressions=_page_count(
            metrics, "productImpressions", "video_product_impressions_cnt"
        ),
        product_clicks=_page_count(
            metrics, "productClicks", "video_product_clicks_cnt"
        ),
        views=_page_count(metrics, "views", "video_views_cnt"),
        likes=_page_count(metrics, "likes", "video_likes_cnt"),
        comments=_page_count(metrics, "comments", "video_comments_cnt"),
        shares=_page_count(metrics, "shares", "video_shares_cnt"),
        product_click_through_rate=rate(
            metrics.get("video_distinct_product_ctr"),
            "productClickThroughRate",
            allow_above_one=True,
        ),
        engagement_rate=rate(
            metrics.get("video_distinct_engagement_rate"),
            "engagementRate",
            allow_above_one=True,
        ),
        finish_rate=rate(
            metrics.get("video_finish_rate"),
            "finishRate",
            allow_above_one=True,
        ),
        extensions=grouped_extensions(
            {
                "performance": (performance, VIDEO_PERFORMANCE_FIELDS),
                "creator_base": (creator, VIDEO_CREATOR_FIELDS),
                "video_info": (video, VIDEO_INFO_FIELDS),
                "play_info": (play_info, VIDEO_PLAY_FIELDS),
                "video_metrics": (metrics, VIDEO_METRIC_FIELDS),
            }
        ),
    )


def _parse_canonical_row(
    row: Mapping[str, object],
    query: AffiliateCenterQuery,
    context: Mapping[str, object],
    *,
    status: str | None = None,
    source_updated_at: datetime | None = None,
) -> AffiliateVideoMetricDTO:
    try:
        currency_code(row.get("currency"), query.currency)
        normalized_status = status or text(row.get("status"), "status")
        normalized_updated_at = timestamp(
            source_updated_at
            if source_updated_at is not None
            else row.get("sourceUpdatedAt"),
            "sourceUpdatedAt",
        )
        return AffiliateVideoMetricDTO(
            video_id=text(row.get("videoId"), "videoId", required=True) or "",
            **context,
            creator_open_id=text(row.get("creatorOpenId"), "creatorOpenId"),
            source_identifiers=source_identifiers(
                official_creator_id=text(row.get("creatorId"), "creatorId")
            ),
            creator_username=text(
                row.get("creatorUsername", row.get("username")), "creatorUsername"
            ),
            creator_nickname=text(row.get("creatorNickname"), "creatorNickname"),
            creator_avatar_url=image_url(
                row.get("creatorAvatarUrl"), "creatorAvatarUrl"
            ),
            creator_follower_count=count(
                row.get("creatorFollowerCount"), "creatorFollowerCount"
            ),
            creator_author_type=text(row.get("creatorAuthorType"), "creatorAuthorType"),
            title=text(row.get("title"), "title"),
            video_post_time=_canonical_timestamp(
                row.get("videoPostTime"), query.shop_timezone
            ),
            duration_seconds=nonnegative_decimal(
                row.get("durationSeconds"), "durationSeconds"
            ),
            cover_image_url=image_url(row.get("coverImageUrl"), "coverImageUrl"),
            play_url=text(row.get("playUrl"), "playUrl"),
            play_id=text(row.get("playId"), "playId"),
            width=count(row.get("width"), "width"),
            height=count(row.get("height"), "height"),
            hashtags=_unique_string_tuple(row.get("hashTags"), "hashTags"),
            promoted_product_ids=string_tuple(
                row.get("promotedProductIds"), "promotedProductIds"
            ),
            promoted_products=parse_canonical_products(row.get("promotedProducts")),
            status=normalized_status,
            source_updated_at=normalized_updated_at,
            **_canonical_metrics(row, query.currency),
            extensions=extensions(row, VIDEO_CANONICAL_FIELDS),
        )
    except (TypeError, ValueError) as error:
        raise AffiliateVideoMetricParseError(str(error)) from error


def _canonical_metrics(
    row: Mapping[str, object], currency: str
) -> dict[str, object]:
    metrics = parse_canonical_video_metrics(row)
    if metrics["gmv_minor"] is None and row.get("gmvAmount") is not None:
        metrics["gmv_minor"] = major_money_minor(
            {
                "amount": row.get("gmvAmount"),
                "currency": row.get("gmvCurrency"),
            },
            currency,
            "gmv",
        )[0]
    if metrics["distinct_gpm_minor"] is None and row.get("gpmAmount") is not None:
        metrics["distinct_gpm_minor"] = major_money_minor(
            {
                "amount": row.get("gpmAmount"),
                "currency": row.get("gpmCurrency"),
            },
            currency,
            "gpm",
        )[0]
    metrics["order_count"] = metrics["order_count"] or count(
        row.get("skuOrders"), "orderCount"
    )
    if metrics["product_click_through_rate"] is None:
        metrics["product_click_through_rate"] = rate(
            row.get("clickThroughRate"),
            "productClickThroughRate",
            allow_above_one=True,
        )
    return metrics


def _canonical_timestamp(value: object, timezone: str) -> datetime | None:
    try:
        return timestamp(value, "videoPostTime")
    except ValueError:
        if not isinstance(value, str):
            raise
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise
        return parsed.replace(tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def _unique_string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field}: expected a list")
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field}: expected an object")
    return value


def _page_money(
    metrics: Mapping[str, object], name: str, currency: str, field: str
) -> int | None:
    value = metrics.get(name)
    if value is None:
        return None
    return major_money_minor(value, currency, field)[0]


def _page_count(metrics: Mapping[str, object], field: str, name: str) -> int | None:
    return count(metrics.get(name), field)
