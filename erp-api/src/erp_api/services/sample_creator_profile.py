from __future__ import annotations

from datetime import datetime
from typing import Any

from erp_api.services.sample_creator_profile_metrics import profile_metric_sections
from erp_api.services.sample_creator_profile_values import (
    as_utc as _as_utc,
)
from erp_api.services.sample_creator_profile_values import (
    avatar_object_key as _avatar_object_key,
)
from erp_api.services.sample_creator_profile_values import (
    basis_points as _basis_points,
)
from erp_api.services.sample_creator_profile_values import (
    distribution_basis_points as _distribution_basis_points,
)
from erp_api.services.sample_creator_profile_values import (
    first as _first,
)
from erp_api.services.sample_creator_profile_values import (
    integer as _integer,
)
from erp_api.services.sample_creator_profile_values import (
    mapping as _mapping,
)
from erp_api.services.sample_creator_profile_values import (
    money_minor as _money_minor,
)
from erp_api.services.sample_creator_profile_values import (
    put as _put,
)
from erp_api.services.sample_creator_profile_values import (
    source_hash as _source_hash,
)
from erp_api.services.sample_creator_profile_values import (
    text as _text,
)
from erp_api.services.sample_creator_profile_values import (
    text_list as _text_list,
)
from erp_api.services.sample_creator_profile_values import (
    without_empty as _without_empty,
)


def normalize_creator_profile(
    creator: dict[str, Any],
    *,
    observed_at: datetime,
    source_type: str,
) -> dict[str, Any]:
    if source_type not in {"official_api", "hubstudio_cdp"}:
        raise ValueError("Creator profile source type is invalid.")
    performance = _mapping(creator.get("performance"))
    profile = _mapping(creator.get("profile"))
    combined = {**creator, **performance, **profile}
    result: dict[str, Any] = {}

    avatar_object_key = _avatar_object_key(combined.get("avatar_object_key"))
    avatar_source_hash = _source_hash(combined.get("avatar_source_hash"))
    if avatar_object_key and avatar_source_hash:
        result.update(
            {
                "creator_avatar_object_key": avatar_object_key,
                "creator_avatar_source_hash": avatar_source_hash,
                "creator_avatar_observed_at": _as_utc(observed_at),
            }
        )

    snapshot = _profile_snapshot(combined)
    if snapshot:
        result.update(
            {
                "creator_profile_snapshot": snapshot,
                "creator_profile_source_type": source_type,
                "creator_profile_observed_at": _as_utc(observed_at),
            }
        )
    return result


def _profile_snapshot(profile: dict[str, Any]) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    _put(snapshot, "bio", _text(profile.get("bio_description") or profile.get("bio")))
    _put(
        snapshot,
        "location",
        _text(profile.get("selection_region") or profile.get("location")),
    )
    _put(
        snapshot,
        "creator_categories",
        _label_items(profile.get("creator_categories")),
    )
    _put(snapshot, "category_ids", _text_list(profile.get("category_ids")))

    category_shares = _distribution(
        profile.get("category_gmv_distribution") or profile.get("categories"),
        label_keys=("name", "category_name", "category_id", "id"),
    )

    content_channels = _distribution(
        profile.get("content_gmv_distribution") or profile.get("channel_shares"),
        label_keys=("name", "content_type", "channel"),
    )
    sales = {
        "gmv_minor": _money_minor(profile.get("gmv")),
        "units_sold": _integer(profile.get("units_sold")),
        "order_count": _integer(profile.get("order_count")),
        "gmv_per_mille_minor": _money_minor(profile.get("gpm")),
        "average_order_value_minor": _money_minor(
            profile.get("avg_gmv_per_buyer") or profile.get("average_order_value")
        ),
        "channel_shares": content_channels,
        "category_shares": category_shares,
        "window": _window(profile.get("sales_window")),
    }
    _put(snapshot, "sales", _without_empty(sales))

    cooperation = {
        "estimated_post_rate_bps": _basis_points(profile.get("post_rate")),
        "average_commission_rate_bps": _basis_points(
            profile.get("avg_commission_rate")
        ),
        "product_count": _integer(
            profile.get("promoted_product_num") or profile.get("product_count")
        ),
        "brand_collaboration_count": _integer(profile.get("brand_collaboration_count")),
        "top_brand_ids": _text_list(profile.get("top_collaborated_brand_ids")),
    }
    _put(snapshot, "cooperation", _without_empty(cooperation))
    snapshot.update(profile_metric_sections(profile))

    audience = _audience(profile)
    _put(snapshot, "audience", audience)

    if snapshot:
        snapshot["schema_version"] = 2
    return snapshot


def _label_items(raw: object) -> list[dict[str, str]] | None:
    if not isinstance(raw, list):
        return None
    result: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            label = _text(item.get("label") or item.get("name"))
            item_id = _text(item.get("id") or item.get("category_id"))
        else:
            label = _text(item)
            item_id = None
        if label:
            result.append({**({"id": item_id} if item_id else {}), "label": label})
    return result or None


def _audience(profile: dict[str, Any]) -> dict[str, object] | None:
    demographics = _mapping(
        profile.get("follower_demographics") or profile.get("audience")
    )
    gender = demographics.get("gender") or profile.get("follower_gender_distribution")
    age = demographics.get("age") or profile.get("follower_age_distribution")
    regions = (
        demographics.get("top_regions")
        or demographics.get("regions")
        or profile.get("follower_region_distribution")
    )
    result = {
        "gender": _distribution(gender, label_keys=("name", "gender", "label")),
        "age": _distribution(age, label_keys=("name", "age", "range", "label")),
        "top_regions": _distribution(
            regions,
            label_keys=("name", "region", "country", "label"),
        ),
        "window": _window(demographics.get("window") or profile.get("audience_window")),
    }
    return _without_empty(result)


def _distribution(
    raw: object,
    *,
    label_keys: tuple[str, ...],
) -> list[dict[str, object]] | None:
    items: list[dict[str, object]] = []
    if isinstance(raw, dict):
        raw = [{"name": key, "percentage": value} for key, value in raw.items()]
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = _text(_first(item, label_keys))
        percentage_source = _first(
            item,
            (
                "percentage",
                "percentage_points",
                "revenue_percentage",
                "gmv_percentage",
                "share",
                "ratio",
                "value",
            ),
        )
        share_bps = _distribution_basis_points(
            percentage_source,
            ratio_key="ratio" in item
            or ("value" in item and "percentage" not in item and "share" not in item),
        )
        if label and share_bps is not None:
            items.append({"code": label, "label": label, "share_bps": share_bps})
    items.sort(key=lambda item: int(item["share_bps"]), reverse=True)
    return items or None


def _window(raw: object) -> dict[str, str] | None:
    value = _mapping(raw)
    allowed = {
        "kind": _text(value.get("kind")),
        "start_at": _text(value.get("start_at")),
        "end_at": _text(value.get("end_at")),
        "timezone": _text(value.get("timezone")),
    }
    return _without_empty(allowed)
