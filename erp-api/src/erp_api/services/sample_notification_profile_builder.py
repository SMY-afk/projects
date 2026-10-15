from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from erp_api.services.affiliate_creator_summary_parser import merge_profile_snapshots

REQUIRED_CREATOR_DETAIL_SOURCES = frozenset(
    {"profile", "performance", "followers", "trends", "examples"}
)


def build_notification_profile_snapshot(application, affiliate=None):
    sales = _without_empty(
        {
            "gmv_minor": application.creator_gmv_minor,
            "units_sold": application.creator_units_sold,
        }
    )
    cooperation = _without_empty(
        {
            "estimated_post_rate_bps": _percentage_bps(
                application.creator_fulfillment_percentage
            ),
        }
    )
    video = _without_empty(
        {
            "count": application.creator_content_count,
            "average_view_count": application.creator_ec_video_view,
        }
    )
    trends = _without_empty(
        {
            "gmv_minor": application.creator_gmv_minor,
            "units_sold": application.creator_units_sold,
            "followers": application.follower_count,
        }
    )
    sections = _without_empty(
        {
            "sales": sales,
            "cooperation": cooperation,
            "video": video,
            "trends": trends,
        }
    )
    base = {"schema_version": 2, **sections} if sections else None
    creator = getattr(affiliate, "creator", None) if affiliate is not None else None
    return merge_profile_snapshots(base, creator_details_snapshot(creator)) or None


def creator_details_snapshot(creator):
    details = _creator_details(creator)
    snapshot = details.get("profile_snapshot") if details else None
    if not isinstance(snapshot, dict):
        return None
    sources = details.get("sources")
    complete = isinstance(sources, dict) and REQUIRED_CREATOR_DETAIL_SOURCES.issubset(
        sources
    )
    return {
        **snapshot,
        **({"creator_details_complete": True} if complete else {}),
    }


def profile_source_type(affiliate) -> str:
    if creator_details_snapshot(affiliate.creator):
        return "hubstudio_cdp"
    raise ValueError("Creator details source is unavailable.")


def profile_observed_at(affiliate):
    if affiliate is None:
        return None
    details = _creator_details(affiliate.creator)
    value = details.get("observed_at") if details else None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return None


def _percentage_bps(value) -> int | None:
    if value is None:
        return None
    return int((Decimal(value) * 100).quantize(Decimal(1)))


def _without_empty(values):
    return {key: value for key, value in values.items() if value not in (None, {}, [])}


def _creator_details(creator):
    extensions = getattr(creator, "extensions", None)
    value = (
        extensions.get("creator_details_summary")
        if isinstance(extensions, dict)
        else None
    )
    return value if isinstance(value, dict) else None
