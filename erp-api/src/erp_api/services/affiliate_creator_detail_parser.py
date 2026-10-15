from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.affiliate_creator_detail_time import detail_window
from erp_api.services.affiliate_metric_parse_support import (
    count,
    image_url,
    major_money_minor,
    rate,
    text,
    timestamp,
)

DETAIL_RESOURCES = frozenset({"video", "live", "product", "product_card"})
_META_FIELDS = {
    "video": ("video_meta", "videoId", ("video_id", "item_id", "id")),
    "live": ("live_meta", "liveId", ("live_id", "room_id", "id")),
    "product": ("product_meta", "productId", ("product_id", "id")),
    "product_card": ("product_meta", "productId", ("product_id", "id")),
}
_MONEY_FIELDS = {
    "gmv": "gmvMinor",
    "direct_gmv": "directGmvMinor",
    "est_commission": "estimatedCommissionMinor",
    "est_flat_fee": "estimatedFlatFeeMinor",
    "refund_gmv": "refundedGmvMinor",
    "main_aov": "averageOrderValueMinor",
    "product_gpm": "productGpmMinor",
    "product_card_gmv": "productCardGmvMinor",
    "product_card_est_commission": "productCardEstimatedCommissionMinor",
    "showcase_gmv": "showcaseGmvMinor",
    "showcase_est_commission": "showcaseEstimatedCommissionMinor",
}
_COUNT_FIELDS = {
    "buyer_cnt": "buyerCount",
    "item_sold_cnt": "itemsSold",
    "paid_main_order_cnt": "orderCount",
    "refund_item_cnt": "refundedItems",
    "video_view_cnt": "views",
    "video_like_cnt": "likes",
    "video_comment_cnt": "comments",
    "video_share_cnt": "shares",
    "product_view_cnt": "productImpressions",
    "product_click_cnt": "productClicks",
    "video_cnt": "videoCount",
    "live_cnt": "liveCount",
    "product_card_buyer_cnt": "productCardBuyerCount",
    "product_card_item_sold_cnt": "productCardItemsSold",
}
_RATE_FIELDS = {"product_ctr": "productClickThroughRate"}
_KNOWN_STAT_FIELDS = frozenset(
    {
        *_MONEY_FIELDS,
        *_COUNT_FIELDS,
        *_RATE_FIELDS,
        "buyer_cnt_daily_avg",
        "video_post_time",
        "live_start_time",
        "creator_meta",
        "linkshare_buyer_cnt",
        "linkshare_est_commission",
        "linkshare_gmv",
        "linkshare_item_sold_cnt",
        "showcase_buyer_cnt",
        "showcase_item_sold_cnt",
        *(value[0] for value in _META_FIELDS.values()),
    }
)


@dataclass(frozen=True)
class CreatorDetailRecord:
    platform_content_id: str
    identity: dict[str, object]
    metrics: dict[str, object]
    extensions: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CreatorDetailPage:
    resource_kind: str
    platform_creator_id: str
    creator_username: str | None
    creator_avatar_url: str | None
    window_start_utc: datetime
    window_end_utc: datetime
    page_number: int
    has_more: bool
    next_page: int | None
    total_count: int | None
    records: tuple[CreatorDetailRecord, ...]


def discriminate_creator_detail(
    path: str, request_body: Mapping[str, object]
) -> str | None:
    prefix = "/api/v2/insights/affiliate/seller/creator_analytics/creator/"
    suffix = path.removeprefix(prefix)
    if suffix == "video/list":
        return "video"
    if suffix == "live/list":
        return "live"
    if suffix != "product/list":
        return None
    params = creator_detail_request_params(request_body)
    filters = params.get("filter")
    if not isinstance(filters, Mapping):
        return None
    return "product" if "only_sample" in filters else "product_card"


def parse_creator_detail_page(
    resource_kind: str,
    payload: Mapping[str, object],
    request_body: Mapping[str, object],
    currency: str,
    *,
    shop_timezone: str | None = None,
) -> CreatorDetailPage:
    if resource_kind not in DETAIL_RESOURCES:
        raise ValueError("Unknown affiliate creator detail resource.")
    params = creator_detail_request_params(request_body)
    filters = _mapping(params.get("filter"), "request.filter")
    creator_id = text(filters.get("creator_id"), "creator_id", required=True) or ""
    pagination = params.get("pagination")
    if not isinstance(pagination, Mapping):
        list_control = _mapping(params.get("list_control"), "request.list_control")
        pagination = _mapping(
            list_control.get("pagination"), "request.list_control.pagination"
        )
    raw_page = count(pagination.get("page"), "page")
    zero_based = "request" in request_body
    page_number = (raw_page or 0) + 1 if zero_based else (raw_page or 1)
    segment = _first_segment(payload)
    descriptor = _mapping(segment.get("time_descriptor"), "time_descriptor")
    start, end = detail_window(descriptor, shop_timezone)
    if end <= start:
        raise ValueError("Creator detail response has an invalid time window.")
    control = _mapping(segment.get("list_control"), "list_control")
    next_pagination = _mapping(
        control.get("next_pagination"), "list_control.next_pagination"
    )
    has_more = bool(next_pagination.get("has_more"))
    next_page = count(next_pagination.get("next_page"), "next_page")
    if zero_based and next_page is not None:
        next_page += 1
    total = count(next_pagination.get("total"), "total")
    stats = _stats(segment)
    creator_meta = next(
        (
            stat["creator_meta"]
            for stat in stats
            if isinstance(stat.get("creator_meta"), Mapping)
        ),
        {},
    )
    assert isinstance(creator_meta, Mapping)
    records = tuple(_record(resource_kind, stat, currency) for stat in stats)
    if has_more and next_page is None:
        raise ValueError("Creator detail response has_more without next_page.")
    return CreatorDetailPage(
        resource_kind=resource_kind,
        platform_creator_id=creator_id,
        creator_username=text(
            creator_meta.get("handle", creator_meta.get("username")), "creatorUsername"
        ),
        creator_avatar_url=image_url(
            creator_meta.get("avatar", creator_meta.get("avatar_url")),
            "creatorAvatarUrl",
        ),
        window_start_utc=start,
        window_end_utc=end,
        page_number=page_number,
        has_more=has_more,
        next_page=next_page,
        total_count=total,
        records=records,
    )


def _record(
    kind: str, stat: Mapping[str, object], currency: str
) -> CreatorDetailRecord:
    meta_field, id_name, id_candidates = _META_FIELDS[kind]
    meta = _mapping(stat.get(meta_field), meta_field)
    content_id = (
        text(
            next((meta[name] for name in id_candidates if name in meta), None),
            id_name,
            required=True,
        )
        or ""
    )
    identity = {
        id_name: content_id,
        "title": text(meta.get("title", meta.get("name")), "title"),
        "coverImageUrl": _cover_image(meta),
    }
    published = timestamp(
        stat.get("video_post_time", stat.get("live_start_time")), "publishedAt"
    )
    if published is not None:
        identity["publishedAt"] = published.isoformat()
    metrics: dict[str, object] = {}
    for source, target in _MONEY_FIELDS.items():
        if source in stat:
            amount, _ = major_money_minor(stat[source], currency, source)
            metrics[target] = amount
    for source, target in _COUNT_FIELDS.items():
        if source in stat:
            metrics[target] = count(stat[source], source)
    for source, target in _RATE_FIELDS.items():
        if source in stat:
            metrics[target] = rate(stat[source], source)
    unknown = {
        key: value for key, value in stat.items() if key not in _KNOWN_STAT_FIELDS
    }
    sanitized = sanitize_capture_payload(unknown)
    return CreatorDetailRecord(
        platform_content_id=content_id,
        identity={key: value for key, value in identity.items() if value is not None},
        metrics=metrics,
        extensions=sanitized if isinstance(sanitized, dict) else {},
    )


def _first_segment(payload: Mapping[str, object]) -> Mapping[str, object]:
    data = _mapping(payload.get("data"), "data")
    segments = data.get("segments")
    if not isinstance(segments, list) or len(segments) != 1:
        raise ValueError("Creator detail response must contain exactly one segment.")
    return _mapping(segments[0], "data.segments[0]")


def _cover_image(meta: Mapping[str, object]) -> str | None:
    direct = meta.get("cover", meta.get("cover_image"))
    if direct is not None:
        return image_url(direct, "coverImageUrl")
    play_info = meta.get("video_play_info")
    if isinstance(play_info, Mapping):
        return text(play_info.get("post_url"), "coverImageUrl")
    return None


def creator_detail_request_params(
    request_body: Mapping[str, object],
) -> Mapping[str, object]:
    if isinstance(request_body.get("filter"), Mapping):
        return request_body
    request = _mapping(request_body.get("request"), "request")
    params = request.get("params")
    if not isinstance(params, list) or len(params) != 1:
        raise ValueError("Creator detail request must contain one params item.")
    return _mapping(params[0], "request.params[0]")


def _stats(segment: Mapping[str, object]) -> list[Mapping[str, object]]:
    timed_lists = segment.get("timed_lists")
    if not isinstance(timed_lists, list) or not timed_lists:
        raise ValueError("Creator detail response is missing timed_lists.")
    result: list[Mapping[str, object]] = []
    for timed in timed_lists:
        values = _mapping(timed, "timed_list").get("stats")
        if values is None and _segment_declares_empty(segment):
            continue
        if not isinstance(values, list):
            raise TypeError("timed_list.stats must be a list.")
        result.extend(_mapping(item, "stat") for item in values)
    return result


def _segment_declares_empty(segment: Mapping[str, object]) -> bool:
    control = segment.get("list_control")
    pagination = (
        control.get("next_pagination") if isinstance(control, Mapping) else None
    )
    total = pagination.get("total") if isinstance(pagination, Mapping) else None
    return total in {0, "0"}


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object.")
    return value
