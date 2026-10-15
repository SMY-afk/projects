from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from backend.app.services.tiktok_sample_creator_details_collector import (
    SampleCreatorDetailsTarget,
)
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.sample_application import SampleApplication
from erp_api.services.sample_bd_assignment import CREATOR_LEVELS
from erp_api.services.sample_notification_profile_builder import (
    creator_details_snapshot,
    profile_observed_at,
)

COMPLETE_PROFILE_RECAPTURE_AGE = timedelta(hours=24)
INCOMPLETE_PROFILE_RETRY_AGE = timedelta(hours=1)
PROFILE_CLOCK_SKEW = timedelta(minutes=1)


class HubStudioSampleProfileTargetProvider:
    """Select fresh pending sample creators whose details need a browser refresh."""

    def __init__(
        self, database, *, activation_at: datetime | None, limit: int = 20
    ) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Sample creator details target limit is invalid.")
        if activation_at is None or activation_at.utcoffset() is None:
            raise ValueError("Sample creator details activation time is invalid.")
        self._database = database
        self._activation_at = activation_at.astimezone(UTC)
        self._limit = limit

    async def list_targets(self, capture) -> list[SampleCreatorDetailsTarget]:
        application_ids = {
            str(item.get("id"))
            for item in capture.page.applications
            if item.get("status") == "PENDING" and item.get("id")
        }
        if not application_ids:
            return []
        statement = (
            select(
                SampleApplication.id,
                SampleApplication.platform_application_id,
                SampleApplication.raw_payload,
                SampleApplication.creator_username,
                SampleApplication.creator_gmv_minor,
                SampleApplication.creator_level,
                SampleApplication.creator_profile_snapshot,
                SampleApplication.creator_profile_observed_at,
                AffiliateCreator.extensions,
            )
            .outerjoin(
                AffiliateCreator,
                and_(
                    AffiliateCreator.tenant_id == SampleApplication.tenant_id,
                    AffiliateCreator.shop_id == SampleApplication.shop_id,
                    or_(
                        and_(
                            SampleApplication.creator_open_id.is_not(None),
                            AffiliateCreator.creator_open_id
                            == SampleApplication.creator_open_id,
                        ),
                        AffiliateCreator.username_normalized
                        == func.lower(
                            func.ltrim(SampleApplication.creator_username, "@")
                        ),
                    ),
                ),
            )
            .where(
                SampleApplication.tenant_id == capture.target.tenant_id,
                SampleApplication.shop_id == capture.target.shop_id,
                SampleApplication.platform_status == "PENDING",
                SampleApplication.is_current_projection.is_(True),
                SampleApplication.tiktok_applied_at >= self._activation_at,
            )
            .order_by(
                SampleApplication.tiktok_applied_at.desc(),
                SampleApplication.platform_application_id.desc(),
            )
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        profile_rows = _matching_profile_rows(rows, application_ids)
        return _targets(profile_rows, now=datetime.now(UTC))[: self._limit]


def _matching_profile_rows(rows, application_ids: set[str]) -> list[tuple]:
    matches = []
    for row in rows:
        outbox_id, platform_application_id, raw_payload, *profile_fields = row
        source_ids = {platform_application_id}
        if isinstance(raw_payload, Mapping):
            raw_source_ids = raw_payload.get("source_item_ids")
            if isinstance(raw_source_ids, Sequence) and not isinstance(
                raw_source_ids, (str, bytes)
            ):
                source_ids.update(
                    value.strip()
                    for value in raw_source_ids
                    if isinstance(value, str) and value.strip()
                )
        if source_ids & application_ids:
            matches.append((outbox_id, *profile_fields))
    return matches


def _targets(rows, *, now: datetime) -> list[SampleCreatorDetailsTarget]:
    grouped: dict[str, set[UUID]] = defaultdict(set)
    for row in rows:
        outbox_id, username, gmv_minor, level, snapshot, observed_at = row[:6]
        if len(row) > 6 and isinstance(row[6], dict):
            creator = SimpleNamespace(extensions=row[6])
            affiliate = SimpleNamespace(creator=creator)
            snapshot = creator_details_snapshot(creator) or snapshot
            observed_at = profile_observed_at(affiliate) or observed_at
        if (
            not isinstance(username, str)
            or not username.strip()
            or not _profile_capture_due(
                gmv_minor,
                level,
                snapshot,
                observed_at,
                now=now,
            )
        ):
            continue
        normalized = username.strip().lstrip("@").casefold()
        grouped[normalized].add(outbox_id)
    return [
        SampleCreatorDetailsTarget(username, frozenset(outbox_ids))
        for username, outbox_ids in grouped.items()
    ]


def _profile_capture_due(
    gmv_minor: object,
    level: object,
    snapshot: object,
    observed_at: datetime | None,
    *,
    now: datetime,
) -> bool:
    if now.tzinfo is None:
        raise ValueError("Creator profile capture time must include a timezone.")
    incomplete = (
        not isinstance(gmv_minor, int)
        or gmv_minor < 0
        or level not in CREATOR_LEVELS
        or not isinstance(snapshot, dict)
        or snapshot.get("creator_details_complete") is not True
    )
    if observed_at is None or observed_at.tzinfo is None:
        return True
    age = now.astimezone(UTC) - observed_at.astimezone(UTC)
    max_age = (
        INCOMPLETE_PROFILE_RETRY_AGE
        if incomplete
        else COMPLETE_PROFILE_RECAPTURE_AGE
    )
    return age < -PROFILE_CLOCK_SKEW or age > max_age
