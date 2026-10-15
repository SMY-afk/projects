from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.shop import Shop
from erp_api.services.refundable_identity_guard import refundable_identity_condition
from erp_api.services.sample_cooperation_records import (
    StoredCooperationAction,
    business_note,
    decision_payload,
    processing_result,
    stored_action,
)
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_DECISION_EVENTS,
    COOPERATION_EVENT_SOURCE,
    COOPERATION_EXCEPTION_EVENT,
    COOPERATION_OWNER_PROTECTED_EVENT,
    COOPERATION_RECENT_EVENT,
    CooperationCandidate,
    CooperationDecision,
)
from erp_api.services.sample_type_policy import REFUNDABLE_ACTIVE_STATUSES

COOPERATION_ACTION_COMPLETED = "sample_cooperation_action_completed"


class SampleCooperationRepository:
    def __init__(
        self,
        database: Database,
        *,
        activation_at: datetime,
        batch_limit: int,
    ) -> None:
        if activation_at.utcoffset() is None or not 1 <= batch_limit <= 500:
            raise ValueError("Sample cooperation repository config is invalid.")
        self._database = database
        self._activation_at = activation_at.astimezone(UTC)
        self._batch_limit = batch_limit

    async def list_candidates(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        application_ids: frozenset[UUID] | None,
    ) -> tuple[CooperationCandidate, ...]:
        if application_ids == frozenset():
            return ()
        previous_decision = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id == SampleApplication.id,
                SampleApplicationEvent.event_source == COOPERATION_EVENT_SOURCE,
                SampleApplicationEvent.event_type.in_(COOPERATION_DECISION_EVENTS),
            )
            .exists()
        )
        previous_assignment = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id == SampleApplication.id,
                SampleApplicationEvent.event_type == "bd_auto_assigned",
                SampleApplicationEvent.event_source == "erp_auto_assignment",
            )
            .exists()
        )
        eligible_since_activation = or_(
            and_(SampleApplication.sample_type == "refundable",
                 SampleApplication.first_seen_at >= self._activation_at),
            and_(
                SampleApplication.source_type == "hubstudio_cdp",
                SampleApplication.tiktok_applied_at >= self._activation_at,
            ),
            and_(
                SampleApplication.source_type == "official_api",
                SampleApplication.first_seen_at >= self._activation_at,
            ),
        )
        statement = (
            select(SampleApplication, SampleApplicationWorkflow, Shop.shop_name)
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
            )
            .join(Shop, Shop.id == SampleApplication.shop_id)
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                or_(
                    and_(SampleApplication.sample_type == "free",
                         SampleApplication.platform_status == "PENDING"),
                    and_(SampleApplication.sample_type == "refundable",
                         SampleApplication.platform_status.in_(REFUNDABLE_ACTIVE_STATUSES)),
                ),
                SampleApplication.is_current_projection.is_(True),
                refundable_identity_condition(SampleApplication),
                or_(SampleApplication.sample_type == "refundable",
                    SampleApplication.raw_payload["is_proactive_invitation"].as_boolean().is_not(None)),
                SampleApplication.raw_payload["manual_assignment_deleted"]
                .as_boolean()
                .is_not(True),
                SampleApplicationWorkflow.assigned_bd_name.is_(None),
                eligible_since_activation,
                ~previous_decision,
                ~previous_assignment,
            )
            .order_by(SampleApplication.source_observed_at, SampleApplication.id)
            .limit(self._batch_limit)
        )
        if application_ids is not None:
            statement = statement.where(SampleApplication.id.in_(application_ids))
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            CooperationCandidate(
                application_id=application.id,
                platform_application_id=application.platform_application_id,
                creator_id=application.creator_username,
                shop_name=shop_name,
                applied_at=application.tiktok_applied_at or application.first_seen_at,
            )
            for application, _workflow, shop_name in rows
        )

    async def record_decisions(self, decisions: tuple[CooperationDecision, ...]) -> int:
        if not decisions:
            return 0
        application_ids = tuple(item.candidate.application_id for item in decisions)
        async with self._database.system_session_factory() as session:
            workflows = {
                item.sample_application_id: item
                for item in (
                    await session.scalars(
                        select(SampleApplicationWorkflow)
                        .where(
                            SampleApplicationWorkflow.sample_application_id.in_(
                                application_ids
                            )
                        )
                        .with_for_update()
                    )
                ).all()
            }
            assigned_ids = set(
                (
                    await session.scalars(
                        select(SampleApplicationEvent.sample_application_id).where(
                            SampleApplicationEvent.sample_application_id.in_(
                                application_ids
                            ),
                            SampleApplicationEvent.event_type == "bd_auto_assigned",
                            SampleApplicationEvent.event_source
                            == "erp_auto_assignment",
                        )
                    )
                ).all()
            )
            recorded = 0
            for decision in decisions:
                workflow = workflows.get(decision.candidate.application_id)
                if (
                    workflow is None
                    or workflow.assigned_bd_name is not None
                    or decision.candidate.application_id in assigned_ids
                ):
                    continue
                await session.execute(
                    insert(SampleApplicationEvent)
                    .values(
                        tenant_id=workflow.tenant_id,
                        shop_id=workflow.shop_id,
                        sample_application_id=decision.candidate.application_id,
                        event_type=decision.event_type,
                        event_source=COOPERATION_EVENT_SOURCE,
                        external_event_id=(
                            f"cooperation-precheck:{decision.candidate.application_id}"
                        ),
                        actor_id="erp-cooperation-precheck",
                        actor_name="ERP Cooperation Precheck",
                        before_data=None,
                        after_data=decision_payload(decision),
                        occurred_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        constraint=(
                            "uq_sample_application_events_tenant_shop_source_external"
                        )
                    )
                )
                if decision.blocks_assignment:
                    workflow.processing_result = processing_result(decision.event_type)
                    workflow.business_note = business_note(decision)
                recorded += 1
            await session.commit()
        return recorded

    async def list_due_actions(
        self, tenant_id: UUID, shop_id: UUID
    ) -> tuple[StoredCooperationAction, ...]:
        decision_event = aliased(SampleApplicationEvent)
        completed = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id
                == decision_event.sample_application_id,
                SampleApplicationEvent.event_type == COOPERATION_ACTION_COMPLETED,
                SampleApplicationEvent.event_source == COOPERATION_EVENT_SOURCE,
            )
            .exists()
        )
        statement = (
            select(
                decision_event,
                SampleApplication,
                SampleApplicationWorkflow,
                Shop.shop_name,
            )
            .join(
                SampleApplication,
                SampleApplication.id == decision_event.sample_application_id,
            )
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
            )
            .join(Shop, Shop.id == SampleApplication.shop_id)
            .where(
                decision_event.tenant_id == tenant_id,
                decision_event.shop_id == shop_id,
                decision_event.event_source == COOPERATION_EVENT_SOURCE,
                decision_event.event_type.in_(
                    (
                        COOPERATION_RECENT_EVENT,
                        COOPERATION_ACTIVE_CREATOR_EVENT,
                        COOPERATION_OWNER_PROTECTED_EVENT,
                        COOPERATION_EXCEPTION_EVENT,
                    )
                ),
                SampleApplicationWorkflow.feishu_record_id.is_not(None),
                refundable_identity_condition(SampleApplication),
                ~completed,
            )
            .order_by(decision_event.occurred_at)
            .limit(self._batch_limit)
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(stored_action(*row) for row in rows)

    async def complete_action(
        self,
        action: StoredCooperationAction,
        *,
        message_ids: tuple[str, ...],
    ) -> None:
        async with self._database.system_session_factory() as session:
            await session.execute(
                insert(SampleApplicationEvent)
                .values(
                    tenant_id=(
                        await session.scalar(
                            select(SampleApplication.tenant_id).where(
                                SampleApplication.id == action.application_id
                            )
                        )
                    ),
                    shop_id=action.shop_id,
                    sample_application_id=action.application_id,
                    event_type=COOPERATION_ACTION_COMPLETED,
                    event_source=COOPERATION_EVENT_SOURCE,
                    external_event_id=f"cooperation-action:{action.application_id}",
                    actor_id="erp-cooperation-precheck",
                    actor_name="ERP Cooperation Precheck",
                    before_data=None,
                    after_data={"message_ids": list(message_ids)},
                    occurred_at=datetime.now(UTC),
                )
                .on_conflict_do_nothing(
                    constraint="uq_sample_application_events_tenant_shop_source_external"
                )
            )
            await session.commit()
