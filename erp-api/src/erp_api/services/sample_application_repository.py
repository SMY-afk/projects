from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import JSON, and_, cast, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.services.sample_application_mapper import normalize_sample_application
from erp_api.services.sample_application_upsert import (
    SamplePayloadObservation,
    build_sample_application_upsert,
    changed_sample_fields,
    sample_event_transition,
)
from erp_api.services.sample_feishu_workflow_change import (
    build_notification_outbox_statements,
    project_workflow_business_fields,
    validate_feishu_business_update,
)


@dataclass(frozen=True)
class SampleSyncRecord:
    application: SampleApplication
    workflow: SampleApplicationWorkflow


class SampleApplicationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_official_payload(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        payload: dict[str, Any],
        observed_at: datetime,
        request_id: str | None,
        source_capture_id: UUID,
    ) -> UUID:
        return await self.upsert_source_payload(
            tenant_id=tenant_id,
            shop_id=shop_id,
            payload=payload,
            observed_at=observed_at,
            request_id=request_id,
            source_capture_id=source_capture_id,
            source_type="official_api",
        )

    async def upsert_source_payload(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        payload: dict[str, Any],
        observed_at: datetime,
        request_id: str | None,
        source_capture_id: UUID,
        source_type: str,
    ) -> UUID:
        application_ids = await self.upsert_source_payloads(
            tenant_id=tenant_id,
            shop_id=shop_id,
            observations=(
                SamplePayloadObservation(
                    payload=payload,
                    observed_at=observed_at,
                    request_id=request_id,
                    source_capture_id=source_capture_id,
                ),
            ),
            source_type=source_type,
        )
        return application_ids[0]

    async def upsert_source_payloads(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        observations: Sequence[SamplePayloadObservation],
        source_type: str,
    ) -> tuple[UUID, ...]:
        if not observations:
            return ()
        async with self._database.system_session_factory() as session:
            application_ids: dict[int, UUID] = {}
            try:
                for index, observation in _ordered_observations(
                    observations, source_type
                ):
                    application_ids[index] = await self._upsert_in_session(
                        session,
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        observation=observation,
                        source_type=source_type,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            return tuple(application_ids[index] for index in range(len(observations)))

    async def list_source_changed_since(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: Sequence[UUID],
        since: datetime,
    ) -> tuple[UUID, ...]:
        if not application_ids:
            return ()
        statement = (
            select(SampleApplication.id)
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplication.id.in_(tuple(application_ids)),
                SampleApplication.source_observed_at >= since,
            )
            .order_by(SampleApplication.id)
        )
        async with self._database.system_session_factory() as session:
            return tuple((await session.scalars(statement)).all())

    @staticmethod
    async def _upsert_in_session(
        session,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        observation: SamplePayloadObservation,
        source_type: str,
    ) -> UUID:
        normalized = normalize_sample_application(
            observation.payload,
            observed_at=observation.observed_at,
            source_type=source_type,
        )
        normalized["source_capture_id"] = observation.source_capture_id
        platform_id = normalized["platform_application_id"]
        existing = await session.scalar(
            select(SampleApplication).where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplication.platform_application_id == platform_id,
            )
        )
        creator = observation.payload.get("creator")
        if existing is not None and (existing.sample_type or "free") != normalized["sample_type"]:
            raise ValueError("Sample application type conflicts with its stored identity")
        performance = creator.get("performance") if isinstance(creator, dict) else None
        performance_fields = (
            frozenset(performance) if isinstance(performance, dict) else frozenset()
        )
        changed_fields = (
            changed_sample_fields(
                existing,
                normalized,
                performance_fields=performance_fields,
            )
            if existing is not None
            else set(normalized) - {"platform_application_id"}
        )
        statement = build_sample_application_upsert(
            tenant_id=tenant_id,
            shop_id=shop_id,
            normalized=normalized,
            observed_at=observation.observed_at,
            changed_fields=changed_fields,
        )
        application_id = await session.scalar(statement)
        if not isinstance(application_id, UUID):
            raise TypeError("Sample application upsert did not return an id.")
        source_item_ids = _group_source_item_ids(observation.payload)
        if source_type == "hubstudio_cdp" and source_item_ids:
            creator_open_id = normalized.get("creator_open_id")
            if not isinstance(creator_open_id, str) or not creator_open_id.strip():
                raise ValueError("Grouped sample creator identity is missing.")
            await session.execute(
                build_group_item_supersede_statement(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    parent_application_id=application_id,
                    parent_platform_application_id=platform_id,
                    source_item_ids=source_item_ids,
                    creator_open_id=creator_open_id,
                    sample_type=normalized["sample_type"],
                )
            )
        workflow_statement = insert(SampleApplicationWorkflow).values(
            tenant_id=tenant_id,
            shop_id=shop_id,
            sample_application_id=application_id,
        )
        await session.execute(
            workflow_statement.on_conflict_do_nothing(
                constraint="uq_sample_application_workflows_application"
            )
        )
        event_type, before_data, after_data = sample_event_transition(
            existing, normalized
        )
        event_id = (
            f"tiktok:{observation.request_id}:{platform_id}"
            if observation.request_id
            else None
        )
        event_statement = insert(SampleApplicationEvent).values(
            tenant_id=tenant_id,
            shop_id=shop_id,
            sample_application_id=application_id,
            event_type=event_type,
            event_source=f"tiktok_{source_type}",
            external_event_id=event_id,
            before_data=before_data,
            after_data=after_data,
            occurred_at=observation.observed_at.astimezone(UTC),
        )
        await session.execute(
            event_statement.on_conflict_do_nothing(
                constraint="uq_sample_application_events_tenant_shop_source_external"
            )
        )
        return application_id

    async def get_sync_record(self, application_id: UUID) -> SampleSyncRecord:
        async with self._database.system_session_factory() as session:
            row = (
                await session.execute(
                    select(SampleApplication, SampleApplicationWorkflow)
                    .join(
                        SampleApplicationWorkflow,
                        SampleApplicationWorkflow.sample_application_id
                        == SampleApplication.id,
                    )
                    .where(SampleApplication.id == application_id)
                )
            ).one_or_none()
            if row is None:
                raise LookupError("Sample application workflow was not found.")
            return SampleSyncRecord(application=row[0], workflow=row[1])

    async def apply_feishu_business_fields(
        self,
        *,
        record_id: str,
        fields: dict[str, Any],
        event_id: str,
        event_source: Literal["feishu_callback", "feishu_poll"],
        actor_id: str | None,
        actor_name: str | None,
        assignment_recipient_open_id: str | None,
        occurred_at: datetime,
    ) -> Literal["applied", "duplicate", "unchanged"]:
        validate_feishu_business_update(
            record_id=record_id,
            fields=fields,
            event_id=event_id,
            event_source=event_source,
            assignment_recipient_open_id=assignment_recipient_open_id,
            occurred_at=occurred_at,
        )
        async with self._database.system_session_factory() as session:
            workflow = await session.scalar(
                select(SampleApplicationWorkflow)
                .where(SampleApplicationWorkflow.feishu_record_id == record_id)
                .with_for_update()
            )
            if workflow is None:
                raise LookupError("Feishu record is not mapped to a workflow.")
            projection = project_workflow_business_fields(workflow, fields)
            before, after = projection.before, projection.after
            stale_poll = (
                event_source == "feishu_poll"
                and workflow.feishu_updated_at is not None
                and occurred_at <= workflow.feishu_updated_at
            )
            if stale_poll:
                after = before
            assignment_changed = not stale_poll and projection.assignment_changed
            event_statement = (
                insert(SampleApplicationEvent)
                .values(
                    tenant_id=workflow.tenant_id,
                    shop_id=workflow.shop_id,
                    sample_application_id=workflow.sample_application_id,
                    event_type=(
                        "business_fields_unchanged"
                        if before == after
                        else "business_fields_changed"
                    ),
                    event_source=event_source,
                    external_event_id=event_id,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    before_data=before,
                    after_data=after,
                    occurred_at=occurred_at.astimezone(UTC),
                )
                .on_conflict_do_nothing(
                    constraint=(
                        "uq_sample_application_events_tenant_shop_source_external"
                    )
                )
                .returning(SampleApplicationEvent.id)
            )
            claimed_event_id = await session.scalar(event_statement)
            if not isinstance(claimed_event_id, UUID):
                await session.rollback()
                return "duplicate"
            if before == after:
                if not stale_poll:
                    workflow.feishu_updated_at = occurred_at.astimezone(UTC)
                await session.commit()
                return "unchanged"
            if assignment_changed:
                workflow.assignment_version += 1
                workflow.assigned_at = occurred_at.astimezone(UTC)
            workflow.assigned_bd_name = after["assigned_bd_name"]
            workflow.processing_status = after["processing_status"]
            workflow.processing_result = after["processing_result"]
            workflow.business_note = after["business_note"]
            workflow.feishu_updated_at = occurred_at.astimezone(UTC)
            if assignment_changed:
                cancel, create = build_notification_outbox_statements(
                    workflow,
                    record_id=record_id,
                    recipient_open_id=assignment_recipient_open_id,
                    event_id=event_id,
                    occurred_at=occurred_at.astimezone(UTC),
                )
                await session.execute(cancel)
                if create is not None:
                    await session.execute(create)
            await session.commit()
            return "applied"


def _group_source_item_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    if "source_item_ids" not in payload:
        return ()
    raw_ids = payload.get("source_item_ids")
    if not isinstance(raw_ids, list):
        raise TypeError("Grouped sample application source items are missing.")
    identities = tuple(
        value.strip() for value in raw_ids if isinstance(value, str) and value.strip()
    )
    if not identities or len(identities) != len(raw_ids) or len(set(identities)) != len(
        identities
    ):
        raise ValueError("Grouped sample application source items are invalid.")
    return identities


def _ordered_observations(
    observations: Sequence[SamplePayloadObservation], source_type: str
) -> tuple[tuple[int, SamplePayloadObservation], ...]:
    indexed = tuple(enumerate(observations))
    if source_type != "hubstudio_cdp":
        return indexed
    return tuple(
        sorted(
            indexed,
            key=lambda item: _group_observation_size(item[1]),
        )
    )


def _group_observation_size(observation: SamplePayloadObservation) -> int:
    source_item_ids = observation.payload.get("source_item_ids")
    return len(source_item_ids) if isinstance(source_item_ids, list) else 0


def build_group_item_supersede_statement(
    *,
    tenant_id: UUID,
    shop_id: UUID,
    parent_application_id: UUID,
    parent_platform_application_id: str,
    source_item_ids: Sequence[str],
    creator_open_id: str,
    sample_type: str = "free",
):
    projection_hint = cast(
        {
            "ziniao_group_projection": {
                "parent_application_id": parent_platform_application_id
            }
        },
        JSONB,
    )
    return (
        update(SampleApplication)
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.sample_type == sample_type,
            or_(
                SampleApplication.platform_application_id.in_(
                    tuple(source_item_ids)
                ),
                and_(
                    SampleApplication.platform_application_id.like(
                        "creator-group:%"
                    ),
                    SampleApplication.creator_open_id == creator_open_id,
                ),
            ),
            SampleApplication.id != parent_application_id,
        )
        .values(
            raw_payload=cast(
                cast(SampleApplication.raw_payload, JSONB).op("||")(
                    projection_hint
                ),
                JSON,
            ),
            is_current_projection=False,
        )
    )
