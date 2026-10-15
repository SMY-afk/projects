from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.affiliate_metric_parse_support import creator_username_key
from erp_api.services.sample_creator_profile_freshness import creator_profile_status
from erp_api.services.sample_notification_profile_builder import (
    build_notification_profile_snapshot,
    creator_details_snapshot,
    profile_observed_at,
    profile_source_type,
)

_PROFILE_GATE_ERRORS = frozenset(
    {"creator_profile_incomplete", "creator_profile_stale"}
)


@dataclass(frozen=True)
class SampleProfileEnrichmentResult:
    enriched_count: int
    unavailable_count: int
    skipped_count: int


class SampleNotificationProfileEnrichmentService:
    def __init__(self, database: Database, *, limit: int = 100) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Sample profile enrichment limit is invalid.")
        self._database = database
        self._limit = limit

    async def enrich(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        outbox_ids: frozenset[UUID] | None = None,
        application_ids: frozenset[UUID] | None = None,
    ) -> SampleProfileEnrichmentResult:
        if outbox_ids is not None and application_ids is not None:
            raise ValueError("Profile enrichment target scopes are mutually exclusive.")
        targets = await self._list_targets(
            tenant_id,
            shop_id,
            outbox_ids,
            application_ids,
        )
        enriched = unavailable = skipped = 0
        for application in targets:
            affiliate = await self._affiliate_context(application)
            snapshot = build_notification_profile_snapshot(application, affiliate)
            if snapshot is None:
                unavailable += 1
                continue
            if await self._persist(application, snapshot, affiliate):
                enriched += 1
            else:
                skipped += 1
            observed_at = profile_observed_at(affiliate) or application.source_observed_at
            if creator_profile_status(
                snapshot,
                observed_at,
                now=datetime.now(UTC),
            ) == "current":
                await self._requeue_profile_gated(application, datetime.now(UTC))
        return SampleProfileEnrichmentResult(enriched, unavailable, skipped)

    async def _list_targets(
        self,
        tenant_id,
        shop_id,
        outbox_ids,
        application_ids=None,
    ):
        if application_ids is not None:
            statement = (
                select(SampleApplication)
                .where(
                    SampleApplication.tenant_id == tenant_id,
                    SampleApplication.shop_id == shop_id,
                    SampleApplication.id.in_(application_ids),
                )
                .order_by(SampleApplication.source_observed_at)
                .limit(self._limit)
            )
            async with self._database.system_session_factory() as session:
                return tuple((await session.execute(statement)).scalars().unique())

        statement = (
            select(SampleApplication)
            .join(
                SampleNotificationOutbox,
                SampleNotificationOutbox.sample_application_id == SampleApplication.id,
            )
            .where(
                SampleNotificationOutbox.tenant_id == tenant_id,
                SampleNotificationOutbox.shop_id == shop_id,
                SampleNotificationOutbox.payload["source_event_id"].astext.like(
                    "bd-auto:%"
                ),
            )
            .order_by(SampleNotificationOutbox.created_at)
            .limit(self._limit)
        )
        if outbox_ids is not None:
            statement = statement.where(SampleNotificationOutbox.id.in_(outbox_ids))
        else:
            statement = statement.where(
                or_(
                    SampleNotificationOutbox.status.in_(("pending", "retry_wait")),
                    and_(
                        SampleNotificationOutbox.status == "failed",
                        SampleNotificationOutbox.last_error_code.in_(
                            _PROFILE_GATE_ERRORS
                        ),
                    ),
                )
            )
        async with self._database.system_session_factory() as session:
            return tuple((await session.execute(statement)).scalars().unique())

    async def _affiliate_context(self, application):
        identities = []
        if application.creator_username:
            identities.append(
                AffiliateCreator.username_normalized
                == creator_username_key(application.creator_username)
            )
        elif application.creator_open_id:
            identities.append(
                AffiliateCreator.creator_open_id == application.creator_open_id
            )
        if not identities:
            return None
        creator_statement = select(AffiliateCreator).where(
            AffiliateCreator.tenant_id == application.tenant_id,
            AffiliateCreator.shop_id == application.shop_id,
            *identities,
        )
        async with self._database.system_session_factory() as session:
            creators = (await session.execute(creator_statement)).scalars().all()
            if len(creators) > 1:
                raise RuntimeError("Sample creator enrichment identity is ambiguous.")
            if not creators:
                return None
            if application.creator_open_id and creators[0].creator_open_id not in {
                None,
                application.creator_open_id,
            }:
                raise RuntimeError("Sample creator enrichment identity conflicts.")
        if creator_details_snapshot(creators[0]):
            return SimpleNamespace(creator=creators[0])
        return None

    async def _persist(self, application, snapshot, affiliate) -> bool:
        async with self._database.system_session_factory() as session:
            target = await session.scalar(
                select(SampleApplication)
                .where(
                    SampleApplication.id == application.id,
                    SampleApplication.tenant_id == application.tenant_id,
                    SampleApplication.shop_id == application.shop_id,
                )
                .with_for_update()
            )
            if target is None:
                raise LookupError("Sample profile enrichment target was not found.")
            observed_at = (
                profile_observed_at(affiliate) or application.source_observed_at
            )
            source_type = (
                profile_source_type(affiliate)
                if affiliate is not None
                else application.source_type
            )
            values = (snapshot, source_type, observed_at)
            current = (
                target.creator_profile_snapshot,
                target.creator_profile_source_type,
                target.creator_profile_observed_at,
            )
            if current == values:
                return False
            (
                target.creator_profile_snapshot,
                target.creator_profile_source_type,
                target.creator_profile_observed_at,
            ) = values
            await session.commit()
            return True

    async def _requeue_profile_gated(self, application, now: datetime) -> int:
        statement = (
            select(SampleNotificationOutbox)
            .where(
                SampleNotificationOutbox.tenant_id == application.tenant_id,
                SampleNotificationOutbox.shop_id == application.shop_id,
                SampleNotificationOutbox.sample_application_id == application.id,
                SampleNotificationOutbox.status == "failed",
                SampleNotificationOutbox.last_error_code.in_(_PROFILE_GATE_ERRORS),
            )
            .with_for_update()
        )
        async with self._database.system_session_factory() as session:
            events = (await session.scalars(statement)).all()
            changed = sum(_requeue_profile_event(event, now) for event in events)
            if changed:
                await session.commit()
            return changed


def _requeue_profile_event(event, now: datetime) -> bool:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if (
        event.status != "failed"
        or event.last_error_code not in _PROFILE_GATE_ERRORS
        or event.sent_at is not None
        or payload.get("message_id") is not None
        or payload.get("group_message_id") is not None
    ):
        return False
    event.status = "pending"
    event.attempt_count = 0
    event.next_attempt_at = now
    event.last_error_code = None
    event.last_error_summary = None
    return True


__all__ = [
    "SampleNotificationProfileEnrichmentService",
    "SampleProfileEnrichmentResult",
    "build_notification_profile_snapshot",
]
