from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from erp_api.models.sample_application import SampleApplication
from erp_api.services.affiliate_metric_parse_support import creator_username_key
from erp_api.services.sample_bd_assignment import classify_creator_level
from erp_api.services.sample_notification_profile_builder import (
    build_notification_profile_snapshot,
    creator_details_snapshot,
    profile_observed_at,
    profile_source_type,
)
from erp_api.services.sample_type_policy import REFUNDABLE_ACTIVE_STATUSES


def pending_creator_sample_applications_statement(
    *,
    tenant_id: UUID,
    shop_id: UUID,
    creator_open_id: str,
    creator_username: str,
):
    username = creator_username_key(creator_username)
    if not creator_open_id or not username:
        raise ValueError("Sample creator identity is incomplete.")
    return select(SampleApplication).where(
        SampleApplication.tenant_id == tenant_id,
        SampleApplication.shop_id == shop_id,
        or_(SampleApplication.platform_status == "PENDING",
            and_(SampleApplication.sample_type == "refundable",
                 SampleApplication.platform_status.in_(REFUNDABLE_ACTIVE_STATUSES))),
        SampleApplication.creator_open_id == creator_open_id,
        func.lower(func.ltrim(SampleApplication.creator_username, "@")) == username,
    )


def apply_latest_creator_profile(applications, creator) -> int:
    affiliate = SimpleNamespace(creator=creator)
    observed_at = profile_observed_at(affiliate)
    if observed_at is None:
        return 0
    source_type = profile_source_type(affiliate)
    details = creator_details_snapshot(creator)
    gmv_minor = _profile_gmv_minor(details)
    updated = 0
    for application in applications:
        current_observed_at = application.creator_profile_observed_at
        if current_observed_at is not None and current_observed_at > observed_at:
            continue
        changed = _backfill_assignment_gmv(application, gmv_minor)
        snapshot = build_notification_profile_snapshot(application, affiliate)
        if snapshot is None:
            updated += int(changed)
            continue
        values = (snapshot, source_type, observed_at)
        current = (
            application.creator_profile_snapshot,
            application.creator_profile_source_type,
            application.creator_profile_observed_at,
        )
        if current == values:
            updated += int(changed)
            continue
        (
            application.creator_profile_snapshot,
            application.creator_profile_source_type,
            application.creator_profile_observed_at,
        ) = values
        updated += 1
    return updated


def _profile_gmv_minor(snapshot: dict[str, object] | None) -> int | None:
    sales = snapshot.get("sales") if isinstance(snapshot, dict) else None
    value = sales.get("gmv_minor") if isinstance(sales, dict) else None
    return value if isinstance(value, int) and value >= 0 else None


def _backfill_assignment_gmv(application, gmv_minor: int | None) -> bool:
    if gmv_minor is None or application.creator_gmv_minor is not None:
        return False
    currency = application.creator_gmv_currency
    if currency not in {None, "USD"}:
        return False
    application.creator_gmv_minor = gmv_minor
    application.creator_gmv_currency = "USD"
    application.creator_level = classify_creator_level(gmv_minor)
    return True
