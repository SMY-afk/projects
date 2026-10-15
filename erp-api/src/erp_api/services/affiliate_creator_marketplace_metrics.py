from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from erp_api.services.sample_creator_profile_values import (
    basis_points,
    integer,
    money_minor,
    text,
)


def performance_source(profile: Mapping[str, object]) -> dict[str, object]:
    window = {"kind": "last_30_days"}
    brands = _value(profile, "partnered_brand")
    return {
        "gmv": _money_value(profile, "med_gmv_revenue"),
        "units_sold": _integer_value(profile, "units_sold"),
        "gpm": _money_value(profile, "gpm"),
        "avg_gmv_per_buyer": _money_value(profile, "avg_revenue_per_buyer"),
        "sales_window": window,
        "post_rate": _integer_value(profile, "sample_fulfillment_rate"),
        "avg_commission_rate": _integer_value(profile, "med_commission_rate"),
        "promoted_product_num": _integer_value(profile, "promoted_product_num"),
        "brand_collaboration_count": _integer_value(profile, "collaborated_brands_num"),
        "top_collaborated_brand_ids": _brand_ids(brands),
        "video_gmv": _money_value(profile, "video_gmv"),
        "video_gpm": _exact_range_money_value(profile, "ec_video_gpm"),
        "video_count": _integer_value(profile, "video_publish_cnt_30d"),
        "avg_video_play_count": _integer_value(profile, "video_play_cnt_med"),
        "video_engagement_rate": _integer_value(profile, "video_engagement"),
        "video_window": window,
        "live_gmv": _money_value(profile, "live_gmv"),
        "live_gpm": _exact_range_money_value(profile, "ec_live_gpm"),
        "live_count": _integer_value(profile, "live_streaming_cnt_30d"),
        "avg_live_play_count": _integer_value(profile, "live_med_view_cnt"),
        "live_engagement_rate": _integer_value(profile, "live_engagement"),
        "live_window": window,
        "sample_score": _sample_score(profile, window),
    }


def performance_extras(profile: Mapping[str, object]) -> dict[str, object]:
    pps = text(_value(profile, "pps_score"))
    return {"pps": {"score": pps} if pps else None}


def trend_snapshot(raw: object) -> dict[str, object]:
    if not isinstance(raw, list):
        raise TypeError("Creator details trend payload must be a list.")
    points = [_trend_point(item) for item in raw if isinstance(item, Mapping)]
    points = [item for item in points if item]
    gmv = [item["gmv_minor"] for item in points if "gmv_minor" in item]
    units = [item["units_sold"] for item in points if "units_sold" in item]
    views = [item["video_views"] for item in points if "video_views" in item]
    followers = [item["followers"] for item in points if "followers" in item]
    rates = [
        item["engagement_rate_bps"] for item in points if "engagement_rate_bps" in item
    ]
    trends = _without_empty(
        {
            "gmv_minor": sum(gmv) if gmv else None,
            "units_sold": sum(units) if units else None,
            "followers": followers[-1] if followers else None,
            "video_views": sum(views) if views else None,
            "engagement_rate_bps": round(sum(rates) / len(rates)) if rates else None,
            "granularity": "day",
            "window": {"kind": "last_30_days"},
            "series": points,
        }
    )
    return {"schema_version": 2, "trends": trends} if trends else {}


def example_videos(profile: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for key in ("top_video_data", "ec_top_video_data"):
        value = _value(profile, key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            item_id = text(item.get("item_id"))
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            result.append(
                _without_empty(
                    {
                        "item_id": item_id,
                        "name": text(item.get("name")),
                        "play_count": _as_integer(item.get("play_cnt")),
                        "like_count": _as_integer(item.get("like_cnt")),
                        "comment_count": _as_integer(item.get("comment_cnt")),
                    }
                )
            )
    return result


def _sample_score(
    profile: Mapping[str, object], window: Mapping[str, object]
) -> dict[str, object]:
    return _without_empty(
        {
            "overall": _value(profile, "sample_credit_total_score"),
            "posting_effect": _value(profile, "sample_credit_fulfillment_score"),
            "posting_freshness": _value(profile, "sample_credit_diligence_score"),
            "selling_power": _value(profile, "sample_credit_sales_ability_score"),
            "content_effect": _value(profile, "sample_credit_content_quality_score"),
            "posting_effect_percentile_bps": _percentile(
                _value(profile, "sample_credit_fulfillment_rank")
            ),
            "posting_freshness_percentile_bps": _percentile(
                _value(profile, "sample_credit_diligence_rank")
            ),
            "selling_power_percentile_bps": _percentile(
                _value(profile, "sample_credit_sales_ability_rank")
            ),
            "content_effect_percentile_bps": _percentile(
                _value(profile, "sample_credit_content_quality_rank")
            ),
            "window": dict(window),
        }
    )


def _trend_point(item: Mapping[str, object]) -> dict[str, object]:
    profile = item.get("profile")
    if not isinstance(profile, Mapping):
        return {}
    return _without_empty(
        {
            "start_at": _timestamp(item.get("start_timestamp")),
            "end_at": _timestamp(item.get("end_timestamp")),
            "gmv_minor": money_minor(_money(_value(profile, "trend_gmv"))),
            "units_sold": _as_integer(_value(profile, "trend_units_sold")),
            "followers": _as_integer(_value(profile, "trend_follower")),
            "video_views": _as_integer(_value(profile, "trend_video_play_cnt")),
            "engagement_rate_bps": basis_points(
                _value(profile, "trend_video_engagement_rate")
            ),
        }
    )


def _value(profile: Mapping[str, object], key: str) -> object:
    item = profile.get(key)
    return item.get("value") if isinstance(item, Mapping) else None


def _integer_value(profile: Mapping[str, object], key: str) -> int | None:
    return _as_integer(_value(profile, key))


def _as_integer(value: object) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return integer(value)


def _money_value(profile: Mapping[str, object], key: str) -> dict[str, object] | None:
    return _money(_value(profile, key))


def _exact_range_money_value(
    profile: Mapping[str, object], key: str
) -> dict[str, object] | None:
    value = _value(profile, key)
    if not isinstance(value, Mapping):
        return _money(value)
    minimum = value.get("minimal", value.get("minimum"))
    maximum = value.get("maximum")
    if minimum in (None, "") or maximum in (None, ""):
        return None
    try:
        if Decimal(str(minimum)) != Decimal(str(maximum)):
            return None
    except (InvalidOperation, ValueError):
        return None
    return {"amount": minimum}


def _money(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping) and value.get("value") not in (None, ""):
        return {"amount": value["value"]}
    return {"amount": value} if value not in (None, "") else None


def _brand_ids(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = [
        item_id
        for item in value
        if isinstance(item, Mapping) and (item_id := text(item.get("id")))
    ]
    return result or None


def _percentile(value: object) -> int | None:
    number = _as_integer(value)
    return number * 100 if number is not None and number <= 100 else number


def _timestamp(value: object) -> str | None:
    if not isinstance(value, int) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _without_empty(values: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value not in (None, {}, [])}
