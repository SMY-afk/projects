"""Keep refundable eligibility separate from free-sample approval semantics."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_

from erp_api.models.sample_application import SampleApplication
from erp_api.services.refundable_identity_guard import (
    quarantined_payload, refundable_identity_condition, valid_unique_username,
)

SAMPLE_TYPES = ("free", "refundable")
SAMPLE_TYPE_LABELS = {"free": "免费样品", "refundable": "买返样品"}
REFUNDABLE_ACTIVE_STATUSES = frozenset(
    {
        "REFUNDABLE_AWAITING_SHIPMENT",
        "REFUNDABLE_SHIPPED",
        "REFUNDABLE_CONTENT_PENDING",
    }
)
REFUNDABLE_SOURCE_MAX_AGE = timedelta(seconds=900)


def sample_activation_condition(activation_at, model=SampleApplication):
    """Official collection starts at discovery; CDP requires source request time."""
    if activation_at.utcoffset() is None:
        raise ValueError("Sample activation time must include a timezone.")
    activation_at = activation_at.astimezone(UTC)
    return or_(
        and_(model.source_type == "official_api", model.first_seen_at >= activation_at),
        and_(
            model.source_type == "hubstudio_cdp",
            model.tiktok_applied_at >= activation_at,
        ),
        and_(model.sample_type == "refundable", model.first_seen_at >= activation_at),
    )


def require_sample_type(value: object) -> str:
    if value not in SAMPLE_TYPES:
        raise ValueError("Sample type is invalid")
    return value


def is_assignable_sample(application, *, now: datetime) -> bool:
    if not application.is_current_projection:
        return False
    kind = getattr(application, "sample_type", None) or "free"
    if kind == "refundable":
        if quarantined_payload(application.raw_payload):
            return False
        if hasattr(application, "creator_username") and not valid_unique_username(application.creator_username):
            return False
        observed = application.source_observed_at
        return (
            application.platform_status in REFUNDABLE_ACTIVE_STATUSES
            and (application.raw_payload or {}).get("refundable_contract_verified")
            is True
            and isinstance(observed, datetime)
            and observed.tzinfo is not None
            and now - REFUNDABLE_SOURCE_MAX_AGE
            <= observed
            <= now + timedelta(seconds=30)
        )
    return (
        kind == "free"
        and application.platform_status == "PENDING"
        and application.is_approvable is True
        and application.approve_expiration_at is not None
        and application.approve_expiration_at > now
    )


def sample_assignment_condition(model=SampleApplication, *, now=None):
    now = now or datetime.now(UTC)
    return or_(
        and_(
            model.sample_type == "free",
            model.platform_status == "PENDING",
            model.is_approvable.is_(True),
            model.approve_expiration_at > now,
        ),
        and_(
            model.sample_type == "refundable",
            refundable_identity_condition(model),
            model.platform_status.in_(REFUNDABLE_ACTIVE_STATUSES),
            model.raw_payload["refundable_contract_verified"].as_boolean().is_(True),
            model.source_observed_at >= now - REFUNDABLE_SOURCE_MAX_AGE,
            model.source_observed_at <= now + timedelta(seconds=30),
        ),
    )
