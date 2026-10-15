from __future__ import annotations

from typing import Any

from erp_api.services.sample_creator_profile_values import (
    basis_points,
    first,
    integer,
    mapping,
    money_minor,
    put,
    score_value,
    text,
    without_empty,
)


def profile_metric_sections(profile: dict[str, Any]) -> dict[str, object]:
    """Normalize optional creator-detail metrics into the snapshot contract."""
    result: dict[str, object] = {}
    put(result, "rating_count", integer(profile.get("rating_count")))
    put(result, "pps", _pps(profile))
    put(result, "sample_score", _sample_score(profile))
    put(result, "video", _content_metrics(profile, "video"))
    put(result, "live", _content_metrics(profile, "live"))
    put(result, "trends", _trends(profile.get("trends")))
    return result


def _pps(profile: dict[str, Any]) -> dict[str, str] | None:
    raw_band = text(first(profile, ("pps_band", "pps_grade", "pps_level")))
    band_code, band_label = _coded_label(raw_band, _PPS_LABELS)
    result = {
        "band_code": band_code,
        "band_label": band_label,
        "description": text(
            first(profile, ("pps_description", "pps_summary", "pps_explanation"))
        ),
    }
    return without_empty(result)


def _sample_score(profile: dict[str, Any]) -> dict[str, object] | None:
    raw = profile.get("sample_score")
    score = mapping(raw)
    if not score and raw not in (None, ""):
        score = {"overall": raw}
    aliases = {
        "overall": ("overall", "score", "total_score"),
        "content_effect": (
            "content_effect",
            "content_effect_score",
            "sample_content_score",
        ),
        "posting_freshness": (
            "posting_freshness",
            "posting_freshness_score",
            "freshness_score",
        ),
        "selling_power": ("selling_power", "selling_power_score"),
        "posting_effect": ("posting_effect", "posting_effect_score"),
    }
    result: dict[str, object] = {
        target: value
        for target, keys in aliases.items()
        if (value := score_value(first(score, keys))) is not None
    }
    raw_grade = text(first(score, ("grade", "level", "label")))
    grade_code, grade_label = _coded_label(raw_grade, _SCORE_LABELS)
    put(result, "grade_code", grade_code)
    put(result, "grade_label", grade_label)
    for metric in (
        "content_effect",
        "posting_freshness",
        "selling_power",
        "posting_effect",
    ):
        percentile = basis_points(score.get(f"{metric}_percentile_bps"))
        put(result, f"{metric}_percentile_bps", percentile)
    put(result, "window", _window(score.get("window")))
    return result or None


def _content_metrics(profile: dict[str, Any], kind: str) -> dict[str, object] | None:
    nested = mapping(profile.get(kind))
    combined = {**profile, **nested}
    prefix = "ec_video" if kind == "video" else "ec_live"
    gmv_keys = (f"{kind}_gmv", "gmv") if nested else (f"{kind}_gmv",)
    gpm_keys = (f"{kind}_gpm", "gpm") if nested else (f"{kind}_gpm",)
    result = {
        "gmv_minor": money_minor(first(combined, gmv_keys)),
        "gmv_per_mille_minor": money_minor(first(combined, gpm_keys)),
        "count": integer(
            first(combined, (f"{kind}_count", f"{prefix}_count", "count"))
        ),
        "average_view_count": integer(
            first(
                combined,
                (
                    f"avg_{kind}_play_count",
                    f"avg_{prefix}_play_count",
                    "average_view_count",
                    "avg_view_count",
                ),
            )
        ),
        "average_engagement_rate_bps": basis_points(
            first(
                combined,
                (
                    f"{kind}_engagement_rate",
                    f"{prefix}_engagement_rate",
                    "average_engagement_rate_bps",
                    "engagement_rate_bps",
                ),
            )
        ),
        "scope": text(first(combined, ("scope", f"{kind}_scope"))),
        "window": _window(nested.get("window") or profile.get(f"{kind}_window")),
    }
    return without_empty(result)


def _trends(raw: object) -> dict[str, object] | None:
    trends = mapping(raw)
    if not trends:
        return None
    result = {
        "gmv_minor": money_minor(trends.get("gmv")),
        "units_sold": integer(trends.get("units_sold")),
        "followers": integer(trends.get("followers")),
        "video_views": integer(trends.get("video_views")),
        "engagement_rate_bps": basis_points(trends.get("engagement_rate_bps")),
        "granularity": text(trends.get("granularity")),
        "window": _window(trends.get("window")),
    }
    return without_empty(result)


def _window(raw: object) -> dict[str, str] | None:
    value = mapping(raw)
    result = {
        "kind": text(value.get("kind")),
        "start_at": text(value.get("start_at")),
        "end_at": text(value.get("end_at")),
        "timezone": text(value.get("timezone")),
    }
    return without_empty(result)


def _coded_label(
    raw: str | None, labels: dict[str, str]
) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    normalized = raw.strip().upper()
    if normalized in labels:
        return normalized, labels[normalized]
    reverse = {label: code for code, label in labels.items()}
    if raw in reverse:
        return reverse[raw], raw
    return normalized[:32], raw[:32]


_PPS_LABELS = {
    "LOW": "较低",
    "MEDIUM": "中等",
    "HIGH": "较高",
    "EXCELLENT": "优秀",
}

_SCORE_LABELS = {
    "POOR": "较差",
    "FAIR": "一般",
    "GOOD": "良好",
    "EXCELLENT": "优秀",
}
