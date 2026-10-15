from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import Insert, insert

from erp_api.models.sample_application import SampleApplication
from erp_api.services.sample_bd_assignment import CREATOR_LEVELS

MANUAL_CREATOR_LEVEL_KEY = "manual_creator_level_override"
MANUAL_ASSIGNMENT_DELETED_KEY = "manual_assignment_deleted"

CREATOR_PROFILE_BUNDLE_FIELDS = frozenset(
    {
        "creator_profile_snapshot",
        "creator_profile_source_type",
        "creator_profile_observed_at",
    }
)
CREATOR_PERFORMANCE_MODEL_FIELDS = {
    "creator_content_count": "ec_video_count",
    "creator_units_sold": "units_sold",
    "creator_pps": "pps",
    "creator_rating": "rating",
}


@dataclass(frozen=True)
class SamplePayloadObservation:
    payload: dict[str, Any]
    observed_at: datetime
    request_id: str | None
    source_capture_id: UUID


def build_sample_application_upsert(
    *,
    tenant_id: UUID,
    shop_id: UUID,
    normalized: dict[str, Any],
    observed_at: datetime,
    changed_fields: set[str],
) -> Insert:
    statement = insert(SampleApplication).values(
        tenant_id=tenant_id,
        shop_id=shop_id,
        first_seen_at=observed_at,
        last_seen_at=observed_at,
        **normalized,
    )
    update_values = {"last_seen_at": statement.excluded.last_seen_at}
    update_values.update(
        {
            key: getattr(statement.excluded, key)
            for key in changed_fields
            if key != "platform_application_id"
        }
    )
    return statement.on_conflict_do_update(
        constraint="uq_sample_applications_tenant_shop_platform_id",
        set_=update_values,
    ).returning(SampleApplication.id)


def changed_sample_fields(
    existing: SampleApplication,
    normalized: dict[str, Any],
    *,
    performance_fields: frozenset[str] | None = None,
) -> set[str]:
    _preserve_existing_sample_score(existing, normalized)
    _preserve_existing_invitation_evidence(existing, normalized)
    _preserve_profile_enriched_gmv(existing, normalized)
    _preserve_manual_creator_level(existing, normalized)
    _preserve_manual_assignment_deletion(existing, normalized)
    _preserve_enriched_application_time(existing, normalized)
    _preserve_ziniao_group_projection(existing, normalized)
    _preserve_verified_approval_deadline(existing, normalized)
    changed = {
        key
        for key, value in normalized.items()
        if key
        not in {
            "platform_application_id",
            "source_capture_id",
            "source_observed_at",
        }
        and getattr(existing, key, None) != value
    }
    existing_snapshot = getattr(existing, "creator_profile_snapshot", None)
    incoming_snapshot = normalized.get("creator_profile_snapshot")
    if _creator_details_complete(existing_snapshot) and not _creator_details_complete(
        incoming_snapshot
    ):
        changed.difference_update(CREATOR_PROFILE_BUNDLE_FIELDS)
    if performance_fields is not None:
        changed.difference_update(
            model_field
            for model_field, source_field in CREATOR_PERFORMANCE_MODEL_FIELDS.items()
            if source_field not in performance_fields
        )
        verified_paid_profile = (
            normalized.get("sample_type") == "refundable"
            and normalized.get("creator_profile_source_type") == "hubstudio_cdp"
            and _creator_details_complete(incoming_snapshot)
        )
        if not performance_fields and not verified_paid_profile:
            changed.difference_update(CREATOR_PROFILE_BUNDLE_FIELDS)
    if changed:
        changed.add("source_observed_at")
    if normalized.get("sample_type") == "refundable":
        changed.add("source_observed_at")
    if getattr(existing, "source_capture_id", None) != normalized.get(
        "source_capture_id"
    ):
        changed.add("source_capture_id")
    return changed


def _preserve_verified_approval_deadline(existing, normalized) -> None:
    if (
        getattr(existing, "platform_status", None) == "PENDING"
        and normalized.get("platform_status") == "PENDING"
        and "approve_expiration_at" in normalized
        and normalized["approve_expiration_at"] is None
        and isinstance(getattr(existing, "approve_expiration_at", None), datetime)
    ):
        normalized["approve_expiration_at"] = existing.approve_expiration_at


def _preserve_profile_enriched_gmv(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    if normalized.get("creator_gmv_minor") is not None:
        return
    existing_gmv = getattr(existing, "creator_gmv_minor", None)
    existing_currency = getattr(existing, "creator_gmv_currency", None)
    existing_level = getattr(existing, "creator_level", None)
    if (
        not isinstance(existing_gmv, int)
        or existing_gmv < 0
        or existing_currency != "USD"
        or existing_level not in CREATOR_LEVELS
    ):
        return
    normalized["creator_gmv_minor"] = existing_gmv
    normalized["creator_gmv_currency"] = existing_currency
    normalized["creator_level"] = existing_level


def _preserve_existing_invitation_evidence(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    incoming = normalized.get("raw_payload")
    previous = getattr(existing, "raw_payload", None)
    if not isinstance(incoming, dict) or not isinstance(previous, dict):
        return
    for key in ("application_source_type", "is_proactive_invitation"):
        if key not in incoming and key in previous:
            incoming[key] = previous[key]


def _preserve_manual_creator_level(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    incoming = normalized.get("raw_payload")
    previous = getattr(existing, "raw_payload", None)
    if not isinstance(incoming, dict) or not isinstance(previous, dict):
        return
    level = previous.get(MANUAL_CREATOR_LEVEL_KEY)
    if level not in CREATOR_LEVELS:
        return
    incoming[MANUAL_CREATOR_LEVEL_KEY] = level
    normalized["creator_level"] = level


def _preserve_manual_assignment_deletion(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    incoming = normalized.get("raw_payload")
    previous = getattr(existing, "raw_payload", None)
    if not isinstance(incoming, dict) or not isinstance(previous, dict):
        return
    if previous.get(MANUAL_ASSIGNMENT_DELETED_KEY) is True:
        incoming[MANUAL_ASSIGNMENT_DELETED_KEY] = True


def _preserve_enriched_application_time(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    if normalized.get("tiktok_applied_at") is not None:
        return
    existing_value = getattr(existing, "tiktok_applied_at", None)
    if existing_value is not None:
        normalized["tiktok_applied_at"] = existing_value


def _preserve_ziniao_group_projection(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    previous = getattr(existing, "raw_payload", None)
    incoming = normalized.get("raw_payload")
    if not isinstance(previous, dict) or not isinstance(incoming, dict):
        return
    projection = previous.get("ziniao_group_projection")
    if not isinstance(projection, dict):
        return
    parent_id = projection.get("parent_application_id")
    platform_id = normalized.get("platform_application_id")
    if not isinstance(parent_id, str) or not isinstance(platform_id, str):
        return
    incoming["ziniao_group_projection"] = projection
    is_parent = platform_id == parent_id
    normalized["is_current_projection"] = is_parent
    if not is_parent:
        return
    for field_name in (
        "platform_status",
        "product_id",
        "product_title",
        "sku_id",
        "sku_name",
        "product_image_urls",
    ):
        if field_name in projection:
            normalized[field_name] = projection[field_name]


def _creator_details_complete(value: object) -> bool:
    return isinstance(value, dict) and value.get("creator_details_complete") is True


def _preserve_existing_sample_score(
    existing: SampleApplication, normalized: dict[str, Any]
) -> None:
    if "creator_profile_snapshot" not in normalized:
        return
    existing_snapshot = getattr(existing, "creator_profile_snapshot", None)
    if not isinstance(existing_snapshot, dict):
        return
    existing_score = existing_snapshot.get("sample_score")
    if not isinstance(existing_score, dict) or not existing_score:
        return
    incoming_snapshot = normalized.get("creator_profile_snapshot")
    merged_snapshot = (
        dict(incoming_snapshot) if isinstance(incoming_snapshot, dict) else {}
    )
    incoming_score = merged_snapshot.get("sample_score")
    merged_score = dict(incoming_score) if isinstance(incoming_score, dict) else {}
    for key, value in existing_score.items():
        if merged_score.get(key) in (None, "", {}, []):
            merged_score[key] = value
    merged_snapshot["sample_score"] = merged_score
    merged_snapshot.setdefault(
        "schema_version", existing_snapshot.get("schema_version", 2)
    )
    normalized["creator_profile_snapshot"] = merged_snapshot


def sample_event_transition(
    existing: SampleApplication | None,
    normalized: dict[str, Any],
) -> tuple[str, dict[str, object] | None, dict[str, object]]:
    after = {"platform_status": normalized["platform_status"]}
    quarantine = (normalized.get("raw_payload") or {}).get("refundable_identity_quarantine")
    if quarantine is not None:
        after["refundable_identity_quarantine"] = quarantine
    if existing is None:
        return "source_ingested", None, after
    before = {"platform_status": existing.platform_status}
    event_type = (
        "platform_status_changed"
        if existing.platform_status != normalized["platform_status"]
        else "source_refreshed"
    )
    return event_type, before, after
