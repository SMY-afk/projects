from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from erp_api.services.affiliate_creator_marketplace_metrics import (
    example_videos,
    performance_extras,
    performance_source,
    trend_snapshot,
)
from erp_api.services.sample_creator_profile import normalize_creator_profile
from erp_api.services.sample_creator_profile_values import integer, text

_PROFILE_KINDS = {
    1: "profile",
    2: "performance",
    3: "followers",
    4: "trends",
    5: "examples",
}


@dataclass(frozen=True)
class MarketplaceProfileSummary:
    resource_kind: str
    platform_creator_id: str
    creator_username: str | None
    profile_snapshot: dict[str, object]


def parse_marketplace_profile(
    payload: Mapping[str, object],
    request_body: Mapping[str, object],
    *,
    observed_at: datetime,
) -> MarketplaceProfileSummary | None:
    profile_type = _profile_type(request_body)
    if profile_type not in _PROFILE_KINDS:
        return None
    creator_id = _find_text(request_body, "creator_oec_id")
    if not creator_id:
        raise ValueError("Creator details request is missing creator_oec_id.")
    kind = _PROFILE_KINDS[profile_type]
    profile = payload.get("creator_profile")
    if kind == "trends":
        snapshot = trend_snapshot(payload.get("creator_profile_trend_data"))
        username = None
    elif not isinstance(profile, Mapping):
        raise TypeError("Creator details profile payload must be an object.")
    else:
        username = text(_value(profile, "handle"))
        snapshot = _profile_snapshot(kind, profile, observed_at)
    return MarketplaceProfileSummary(
        kind,
        creator_id,
        username.lstrip("@") if username else None,
        snapshot,
    )


def _profile_snapshot(
    kind: str, profile: Mapping[str, object], observed_at: datetime
) -> dict[str, object]:
    if kind == "profile":
        source = {
            "bio": _value(profile, "bio"),
            "selection_region": _value(profile, "selection_region"),
            "creator_categories": _categories(_value(profile, "category")),
            "rating_count": _integer_value(profile, "creator_fulfillment_reviews"),
        }
        extras = {
            "follower_count": _integer_value(profile, "follower_cnt"),
        }
    elif kind == "performance":
        source = performance_source(profile)
        extras = performance_extras(profile)
    elif kind == "followers":
        source = {
            "follower_gender_distribution": _distribution(
                _value(profile, "follower_genders_v2"), normalize_unit_ratios=True
            ),
            "follower_age_distribution": _distribution(
                _value(profile, "follower_ages_v2"), round_unit_total=True
            ),
            "follower_region_distribution": _distribution(
                _value(profile, "follower_state_location"), basis_point_values=True
            ),
            "audience_window": {"kind": "last_30_days"},
        }
        extras = {}
    else:
        source = {}
        extras = {"example_videos": example_videos(profile)}
    normalized = normalize_creator_profile(
        _without_empty(source),
        observed_at=observed_at,
        source_type="hubstudio_cdp",
    ).get("creator_profile_snapshot")
    snapshot = dict(normalized) if isinstance(normalized, Mapping) else {}
    if kind == "followers":
        _order_audience(snapshot)
    snapshot.update(_without_empty(extras))
    if snapshot:
        snapshot["schema_version"] = 2
    return snapshot


def _profile_type(body: Mapping[str, object]) -> int | None:
    value = body.get("profile_types")
    return value[0] if isinstance(value, list) and len(value) == 1 else None


def _value(profile: Mapping[str, object], key: str) -> object:
    item = profile.get(key)
    return item.get("value") if isinstance(item, Mapping) else None


def _integer_value(profile: Mapping[str, object], key: str) -> int | None:
    return _as_integer(_value(profile, key))


def _as_integer(value: object) -> int | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    return integer(value)


def _categories(value: object) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    result = []
    for item in value:
        if not isinstance(item, Mapping) or not (label := text(item.get("name"))):
            continue
        item_id = text(item.get("starling_key"))
        result.append({**({"id": item_id} if item_id else {}), "label": label})
    return result or None


def _distribution(
    value: object,
    *,
    normalize_unit_ratios: bool = False,
    round_unit_total: bool = False,
    basis_point_values: bool = False,
) -> list[dict[str, object]] | None:
    if not isinstance(value, list):
        return None
    parsed: list[tuple[str, Decimal]] = []
    for item in value:
        if not isinstance(item, Mapping) or not (label := text(item.get("key"))):
            continue
        try:
            number = Decimal(str(item.get("value")))
        except (InvalidOperation, ValueError):
            continue
        if not number.is_finite() or number < 0:
            continue
        parsed.append((label, number))
    if not parsed:
        return None
    values = [number for _label, number in parsed]
    if normalize_unit_ratios and all(number <= 1 for number in values):
        total = sum(values)
        if total <= 0:
            return None
        percentages = [number * 100 / total for number in values]
    elif round_unit_total and all(number <= 1 for number in values):
        rounded_bps = [
            int((number * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            * 10
            for number in values
        ]
        residual = 10_000 - sum(rounded_bps)
        if abs(residual) <= 50:
            rounded_bps[values.index(max(values))] += residual
        percentages = [Decimal(value) / 100 for value in rounded_bps]
    elif basis_point_values and all(number <= 10_000 for number in values):
        percentages = [number / 100 for number in values]
    else:
        percentages = values
    return [
        {"name": label, "percentage": format(percentage, "f")}
        for (label, _number), percentage in zip(parsed, percentages, strict=True)
    ]


def _order_audience(snapshot: dict[str, object]) -> None:
    audience = snapshot.get("audience")
    if not isinstance(audience, dict):
        return
    gender = audience.get("gender")
    if isinstance(gender, list):
        labels = {"male": "Male", "female": "Female"}
        for item in gender:
            if isinstance(item, dict) and isinstance(item.get("code"), str):
                item["label"] = labels.get(item["code"].casefold(), item["code"])
        gender.sort(
            key=lambda item: {"male": 0, "female": 1}.get(
                str(item.get("code", "")).casefold(), 2
            )
        )
    age = audience.get("age")
    if isinstance(age, list):
        order = {label: index for index, label in enumerate(
            ("18-24", "25-34", "35-44", "45-54", "55+")
        )}
        age.sort(key=lambda item: order.get(str(item.get("code", "")), 99))


def _find_text(value: object, key: str) -> str | None:
    if isinstance(value, Mapping):
        found = value.get(key)
        if result := text(found):
            return result
        for item in value.values():
            if result := _find_text(item, key):
                return result
    elif isinstance(value, list):
        for item in value:
            if result := _find_text(item, key):
                return result
    return None


def _without_empty(values: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value not in (None, {}, [])}
