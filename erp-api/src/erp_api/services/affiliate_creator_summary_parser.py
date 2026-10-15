from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.affiliate_creator_marketplace_profile import (
    parse_marketplace_profile,
)
from erp_api.services.affiliate_metric_parse_support import creator_username_key
from erp_api.services.sample_creator_profile import normalize_creator_profile

_SUMMARY_PATHS = {
    "/oec/affiliate/creator/marketplace/profile": "profile",
    "/oec/affiliate/creator/marketplace/creator/profile/stats": "collaboration",
    "/oec/affiliate/cmp/creator/ec/stats": "sales",
    "/oec/affiliate/creator/marketplace/content/stats": "content",
    "/oec/affiliate/creator/marketplace/follower/stats": "followers",
}
_LEGACY_SUFFIXES = {
    "sales/stats": "sales",
    "collab/stats": "collaboration",
    "video/stats": "content",
    "live/stats": "content",
    "follower/stats": "followers",
    "trend/stats": "content",
}
_COMMON_FIELDS = {
    "bio_description",
    "selection_region",
    "creator_categories",
    "category_ids",
}
_FIELDS = {
    "sales": {
        "gmv",
        "units_sold",
        "order_count",
        "gpm",
        "avg_gmv_per_buyer",
        "average_order_value",
        "content_gmv_distribution",
        "channel_shares",
        "category_gmv_distribution",
        "categories",
        "sales_window",
    },
    "collaboration": {
        "post_rate",
        "avg_commission_rate",
        "promoted_product_num",
        "product_count",
        "brand_collaboration_count",
        "top_collaborated_brand_ids",
    },
    "profile": _COMMON_FIELDS,
    "followers": {
        "follower_demographics",
        "follower_gender_distribution",
        "follower_age_distribution",
        "follower_region_distribution",
        "audience_window",
    },
}


@dataclass(frozen=True)
class CreatorSummaryPayload:
    resource_kind: str
    platform_creator_id: str
    creator_open_id: str | None
    creator_username: str | None
    profile_snapshot: dict[str, object]
    raw_data: dict[str, object]
    observed_at: datetime


def discriminate_creator_summary(path: str) -> str | None:
    normalized = re.sub(r"^/api/v\d+", "", path.rstrip("/"))
    if normalized in _SUMMARY_PATHS:
        return _SUMMARY_PATHS[normalized]
    prefix = "/insights/affiliate/seller/creator_analytics/creator/"
    if normalized.startswith(prefix):
        return _LEGACY_SUFFIXES.get(normalized.removeprefix(prefix))
    return None


def parse_creator_summary(
    resource_kind: str,
    payload: Mapping[str, object],
    request_body: Mapping[str, object],
    *,
    observed_at: datetime,
) -> CreatorSummaryPayload:
    if resource_kind not in {*_FIELDS, "content"}:
        raise ValueError("Unknown affiliate creator summary resource.")
    marketplace = (
        parse_marketplace_profile(
            payload,
            request_body,
            observed_at=observed_at,
        )
        if resource_kind == "profile"
        else None
    )
    if marketplace is not None:
        sanitized = sanitize_capture_payload(payload)
        if not isinstance(sanitized, dict):
            raise TypeError("Creator summary sanitization failed.")
        return CreatorSummaryPayload(
            resource_kind=marketplace.resource_kind,
            platform_creator_id=marketplace.platform_creator_id,
            creator_open_id=None,
            creator_username=marketplace.creator_username,
            profile_snapshot=marketplace.profile_snapshot,
            raw_data=sanitized,
            observed_at=observed_at,
        )
    creator_id = _find_text(request_body, {"creator_id", "creatorid"})
    if not creator_id:
        raise ValueError("Creator summary request is missing creator_id.")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise TypeError("Creator summary response data must be an object.")
    normalized = _snake_keys(data)
    profile_input = _profile_input(resource_kind, normalized)
    profile_result = normalize_creator_profile(
        profile_input,
        observed_at=observed_at,
        source_type="hubstudio_cdp",
    )
    snapshot = profile_result.get("creator_profile_snapshot") or {}
    sanitized = sanitize_capture_payload(data)
    if not isinstance(snapshot, dict) or not isinstance(sanitized, dict):
        raise TypeError("Creator summary normalization failed.")
    username = _find_text(normalized, {"username", "handle"})
    return CreatorSummaryPayload(
        resource_kind=resource_kind,
        platform_creator_id=creator_id,
        creator_open_id=_find_text(
            normalized, {"creator_open_id", "creatoropen_id", "creatoropenid"}
        ),
        creator_username=username.lstrip("@") if username else None,
        profile_snapshot=snapshot,
        raw_data=sanitized,
        observed_at=observed_at,
    )


def validate_creator_summary_identity(
    *,
    expected_open_id: str,
    expected_username: str,
    expected_shop_id: str,
    actual_open_id: str,
    actual_username: str,
    actual_shop_id: str,
) -> None:
    if expected_open_id != actual_open_id:
        raise ValueError("Creator summary creator_open_id does not match.")
    if creator_username_key(expected_username) != creator_username_key(actual_username):
        raise ValueError("Creator summary username does not match.")
    if expected_shop_id != actual_shop_id:
        raise ValueError("Creator summary shop does not match.")


def merge_profile_snapshots(
    current: Mapping[str, object] | None,
    incoming: Mapping[str, object] | None,
) -> dict[str, object]:
    result = _merge_mappings(current, incoming)
    if result:
        result["schema_version"] = 2
    return result


def _merge_mappings(
    current: Mapping[str, object] | None,
    incoming: Mapping[str, object] | None,
) -> dict[str, object]:
    result = dict(current or {})
    for key, value in (incoming or {}).items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = _merge_mappings(existing, value)
        elif value not in (None, {}, []):
            result[key] = value
    return result


def _profile_input(kind: str, data: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    fields = _COMMON_FIELDS | _FIELDS.get(kind, set())
    for field in fields:
        value = _find_value(data, field)
        if value not in (None, "", {}, []):
            result[field] = value
    if kind == "content":
        for section in ("video", "live", "trends"):
            value = _find_value(data, section)
            if isinstance(value, Mapping):
                result[section] = dict(value)
        for field in (
            "video_gmv",
            "video_gpm",
            "ec_video_count",
            "avg_ec_video_play_count",
            "ec_video_engagement_rate",
            "video_window",
            "live_gmv",
            "live_gpm",
            "ec_live_count",
            "avg_ec_live_play_count",
            "ec_live_engagement_rate",
            "live_window",
        ):
            value = _find_value(data, field)
            if value not in (None, "", {}, []):
                result[field] = value
    return result


def _snake_keys(value: object) -> object:
    if isinstance(value, Mapping):
        return {_snake(str(key)): _snake_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snake_keys(item) for item in value]
    return value


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).casefold()


def _find_text(value: object, keys: set[str]) -> str | None:
    found = _find_any(value, keys)
    if isinstance(found, (str, int)) and (text := str(found).strip()):
        return text
    return None


def _find_value(value: object, key: str) -> object:
    return _find_any(value, {key})


def _find_any(value: object, keys: set[str]) -> object:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = _snake(str(key))
            if normalized in keys or normalized.replace("_", "") in keys:
                return item
        for item in value.values():
            found = _find_any(item, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_any(item, keys)
            if found is not None:
                return found
    return None
