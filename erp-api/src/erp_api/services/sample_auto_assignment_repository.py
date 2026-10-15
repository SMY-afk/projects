from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import and_, case, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import aliased

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_auto_assignment_service import PendingSampleAssignment
from erp_api.services.sample_bd_assignment import (
    CREATOR_LEVELS,
    AssignmentDecision,
    BdWorkload,
)
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ALLOWED_EVENT,
    COOPERATION_EVENT_SOURCE,
)
from erp_api.services.sample_feishu_workflow_change import (
    build_notification_outbox_statements,
)
from erp_api.services.sample_type_policy import (
    is_assignable_sample,
    sample_assignment_condition,
)


class SampleAutoAssignmentRepository:
    def __init__(
        self,
        database: Database,
        *,
        category: str,
        batch_limit: int,
        activation_at: datetime,
    ) -> None:
        if not category.strip() or not 1 <= batch_limit <= 100:
            raise ValueError("Sample auto-assignment repository config is invalid.")
        if activation_at.utcoffset() is None:
            raise ValueError("Sample auto-assignment activation time is invalid.")
        self._database = database
        self._category = category.strip()
        self._batch_limit = batch_limit
        self._activation_at = activation_at.astimezone(UTC)

    async def list_pending(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        application_ids: frozenset[UUID] | None = None,
        exclude_previously_blocked: bool = False,
    ) -> tuple[PendingSampleAssignment, ...]:
        hubstudio_identity = SampleApplication.source_type == "hubstudio_cdp"
        official_identity = SampleApplication.source_type == "official_api"
        eligible_since_activation = or_(
            and_(SampleApplication.sample_type == "refundable",
                 SampleApplication.first_seen_at >= self._activation_at),
            and_(
                hubstudio_identity,
                SampleApplication.tiktok_applied_at >= self._activation_at,
            ),
            and_(
                official_identity,
                SampleApplication.first_seen_at >= self._activation_at,
            ),
        )
        creator_identity = func.coalesce(
            func.nullif(SampleApplication.creator_open_id, ""),
            func.lower(func.trim(SampleApplication.creator_username)),
            SampleApplication.platform_application_id,
        )
        discovery_batch = case(
            (official_identity, SampleApplication.first_seen_at),
            else_=None,
        )
        previous_auto_assignment = (
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
        previous_auto_block = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id == SampleApplication.id,
                SampleApplicationEvent.event_type == "bd_auto_blocked",
                SampleApplicationEvent.event_source == "erp_auto_assignment",
            )
            .exists()
        )
        cooperation_allowed = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id == SampleApplication.id,
                SampleApplicationEvent.event_type == COOPERATION_ALLOWED_EVENT,
                SampleApplicationEvent.event_source == COOPERATION_EVENT_SOURCE,
            )
            .exists()
        )
        previous_notification_delivery = (
            select(SampleNotificationOutbox.id)
            .where(
                SampleNotificationOutbox.tenant_id == tenant_id,
                SampleNotificationOutbox.shop_id == shop_id,
                SampleNotificationOutbox.sample_application_id
                == SampleApplication.id,
                or_(
                    SampleNotificationOutbox.status == "sent",
                    SampleNotificationOutbox.sent_at.is_not(None),
                    SampleNotificationOutbox.payload["message_id"]
                    .astext.is_not(None),
                    SampleNotificationOutbox.payload["message_sent_at"]
                    .astext.is_not(None),
                ),
            )
            .exists()
        )
        group_member = aliased(SampleApplication)
        invalid_group_member = (
            select(group_member.id)
            .where(
                group_member.tenant_id == SampleApplication.tenant_id,
                group_member.shop_id == SampleApplication.shop_id,
                cast(group_member.raw_payload, JSONB)[
                    ("ziniao_group_projection", "parent_application_id")
                ].astext
                == SampleApplication.platform_application_id,
                or_(
                    group_member.platform_status != "PENDING",
                    group_member.is_approvable.is_not(True),
                    group_member.approve_expiration_at.is_(None),
                    group_member.approve_expiration_at <= datetime.now(UTC),
                ),
            )
            .exists()
        )
        ranked_statement = (
            select(
                SampleApplication.id.label("application_id"),
                func.row_number()
                .over(
                    partition_by=(creator_identity, discovery_batch, SampleApplication.sample_type),
                    order_by=(
                        func.coalesce(
                            SampleApplication.tiktok_applied_at,
                            SampleApplication.first_seen_at,
                        ).desc(),
                        SampleApplication.id,
                    ),
                )
                .label("identity_rank"),
            )
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
            )
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplication.is_current_projection.is_(True),
                sample_assignment_condition(),
                ~invalid_group_member,
                or_(SampleApplication.sample_type == "refundable",
                    SampleApplication.raw_payload["is_proactive_invitation"].as_boolean().is_not(None)),
                SampleApplication.raw_payload["manual_assignment_deleted"]
                .as_boolean()
                .is_not(True),
                SampleApplicationWorkflow.feishu_record_id.is_not(None),
                cooperation_allowed,
                ~previous_auto_assignment,
                ~previous_notification_delivery,
            )
        )
        if application_ids is None:
            ranked_statement = ranked_statement.where(eligible_since_activation)
        else:
            ranked_statement = ranked_statement.where(
                SampleApplication.id.in_(application_ids)
            )
        if exclude_previously_blocked:
            ranked_statement = ranked_statement.where(~previous_auto_block)
        ranked = ranked_statement.subquery()
        statement = (
            select(SampleApplication, SampleApplicationWorkflow)
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
            )
            .join(
                ranked,
                and_(
                    ranked.c.application_id == SampleApplication.id,
                    ranked.c.identity_rank == 1,
                ),
            )
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplicationWorkflow.assigned_bd_name.is_(None),
            )
            .order_by(SampleApplication.source_observed_at, SampleApplication.id)
            .limit(self._batch_limit)
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
            average_rows = (
                await session.execute(
                    select(
                        SampleApplication.creator_level,
                        SampleApplication.sample_type,
                        func.avg(SampleApplication.creator_gmv_minor),
                    )
                    .where(
                        SampleApplication.tenant_id == tenant_id,
                        SampleApplication.shop_id == shop_id,
                        SampleApplication.is_current_projection.is_(True),
                        SampleApplication.first_seen_at
                        >= datetime.now(UTC) - timedelta(days=30),
                        SampleApplication.creator_level.in_(CREATOR_LEVELS),
                        SampleApplication.creator_gmv_minor.is_not(None),
                        SampleApplication.creator_gmv_minor >= 0,
                        SampleApplication.creator_gmv_currency == "USD",
                    )
                    .group_by(SampleApplication.creator_level, SampleApplication.sample_type)
                )
            ).all()
        recent_averages = {
            (level, sample_type): int(
                Decimal(str(average)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
            for level, sample_type, average in average_rows
            if level in CREATOR_LEVELS and average is not None
        }
        return tuple(
            PendingSampleAssignment(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_id=application.id,
                creator_level=application.creator_level,
                category=self._category,
                assignment_key=_creator_assignment_key(application),
                creator_gmv_minor=application.creator_gmv_minor,
                estimated_level_gmv_minor=recent_averages.get(
                    (application.creator_level, application.sample_type)
                ),
                sample_type=application.sample_type,
            )
            for application, _workflow in rows
        )

    @asynccontextmanager
    async def transaction(self, request: PendingSampleAssignment):
        async with self._database.system_session_factory() as session:
            transaction = _SampleAssignmentTransaction(session, request)
            await transaction.lock()
            try:
                yield transaction
                await session.commit()
            except Exception:
                await session.rollback()
                raise


class _SampleAssignmentTransaction:
    def __init__(self, session, request: PendingSampleAssignment) -> None:
        self._session = session
        self._request = request
        self._application = None
        self._workflow = None
        self._compensation_external_id: str | None = None

    async def lock(self) -> None:
        creator_lock_key = (
            f"sample-assignment:{self._request.tenant_id}:"
            f"{self._request.assignment_key}"
        )
        await self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(literal(creator_lock_key), 0)
                )
            )
        )
        self._application = await self._session.scalar(
            select(SampleApplication)
            .where(
                SampleApplication.tenant_id == self._request.tenant_id,
                SampleApplication.shop_id == self._request.shop_id,
                SampleApplication.id == self._request.application_id,
            )
            .with_for_update()
        )
        if self._application is None:
            raise LookupError("Sample assignment application was not found.")
        self._workflow = await self._session.scalar(
            select(SampleApplicationWorkflow)
            .where(
                SampleApplicationWorkflow.tenant_id == self._request.tenant_id,
                SampleApplicationWorkflow.shop_id == self._request.shop_id,
                SampleApplicationWorkflow.sample_application_id
                == self._request.application_id,
            )
            .with_for_update()
        )
        if self._workflow is None:
            raise LookupError("Sample assignment workflow was not found.")

    async def is_assigned(self) -> bool:
        if (self._application.raw_payload or {}).get(
            "manual_assignment_deleted"
        ) is True:
            return True
        if not is_assignable_sample(self._application, now=datetime.now(UTC)):
            return True
        group_ids = (
            (self._application.raw_payload or {})
            .get("ziniao_group_projection", {})
            .get("source_item_ids", ())
        )
        if isinstance(group_ids, list) and len(group_ids) > 1:
            members = (
                await self._session.execute(
                    select(
                        SampleApplication.platform_application_id,
                        SampleApplication.platform_status,
                        SampleApplication.is_approvable,
                        SampleApplication.approve_expiration_at,
                    ).where(
                        SampleApplication.tenant_id == self._request.tenant_id,
                        SampleApplication.shop_id == self._request.shop_id,
                        SampleApplication.platform_application_id.in_(group_ids),
                    )
                )
            ).all()
            if len(members) != len(set(group_ids)) or any(
                status != "PENDING"
                or approvable is not True
                or expires_at is None
                or expires_at <= datetime.now(UTC)
                for _source_id, status, approvable, expires_at in members
            ):
                return True
        if self._workflow.assigned_bd_name is not None:
            return True
        historical_assignment_id = await self._session.scalar(
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == self._request.tenant_id,
                SampleApplicationEvent.shop_id == self._request.shop_id,
                SampleApplicationEvent.sample_application_id
                == self._request.application_id,
                SampleApplicationEvent.event_type == "bd_auto_assigned",
                SampleApplicationEvent.event_source == "erp_auto_assignment",
            )
            .limit(1)
        )
        if historical_assignment_id is not None:
            return True
        historical_delivery_id = await self._session.scalar(
            select(SampleNotificationOutbox.id)
            .where(
                SampleNotificationOutbox.tenant_id == self._request.tenant_id,
                SampleNotificationOutbox.shop_id == self._request.shop_id,
                SampleNotificationOutbox.sample_application_id
                == self._request.application_id,
                or_(
                    SampleNotificationOutbox.status == "sent",
                    SampleNotificationOutbox.sent_at.is_not(None),
                    SampleNotificationOutbox.payload["message_id"]
                    .astext.is_not(None),
                    SampleNotificationOutbox.payload["message_sent_at"]
                    .astext.is_not(None),
                ),
            )
            .limit(1)
        )
        return historical_delivery_id is not None

    async def load_creator_bd_name(self) -> str | None:
        key_type, separator, identity = self._request.assignment_key.partition(":")
        if not separator or not identity or key_type == "application":
            return None
        historical_application = aliased(SampleApplication)
        if key_type == "open":
            creator_match = historical_application.creator_open_id == identity
        elif key_type == "username":
            creator_match = (
                func.lower(
                    func.ltrim(func.trim(historical_application.creator_username), "@")
                )
                == identity
            )
        else:
            raise ValueError("Sample creator assignment key is invalid.")
        statement = (
            select(SampleApplicationWorkflow.assigned_bd_name)
            .join(
                historical_application,
                historical_application.id
                == SampleApplicationWorkflow.sample_application_id,
            )
            .where(
                SampleApplicationWorkflow.tenant_id == self._request.tenant_id,
                SampleApplicationWorkflow.sample_application_id
                != self._request.application_id,
                SampleApplicationWorkflow.assigned_bd_name.is_not(None),
                SampleApplicationWorkflow.assigned_at
                >= datetime.now(UTC) - timedelta(days=7),
                creator_match,
            )
            .order_by(
                SampleApplicationWorkflow.assigned_at.asc().nulls_last(),
                historical_application.first_seen_at,
                historical_application.id,
            )
            .limit(1)
        )
        sent_assignment = (
            select(SampleApplicationEvent.after_data["assigned_bd_name"].astext)
            .join(
                historical_application,
                historical_application.id == SampleApplicationEvent.sample_application_id,
            )
            .where(
                SampleApplicationEvent.tenant_id == self._request.tenant_id,
                SampleApplicationEvent.sample_application_id != self._request.application_id,
                SampleApplicationEvent.event_type == "bd_auto_assigned",
                SampleApplicationEvent.event_source == "erp_auto_assignment",
                SampleApplicationEvent.occurred_at >= datetime.now(UTC) - timedelta(days=7),
                creator_match,
                func.coalesce(
                    historical_application.raw_payload["manual_assignment_deleted"].as_string(),
                    "false",
                ) != "true",
                select(SampleNotificationOutbox.id)
                .where(
                    SampleNotificationOutbox.tenant_id == SampleApplicationEvent.tenant_id,
                    SampleNotificationOutbox.shop_id == SampleApplicationEvent.shop_id,
                    SampleNotificationOutbox.sample_application_id
                    == SampleApplicationEvent.sample_application_id,
                    SampleNotificationOutbox.status == "sent",
                    SampleNotificationOutbox.payload["assigned_bd_name"].astext
                    == SampleApplicationEvent.after_data["assigned_bd_name"].astext,
                )
                .exists(),
            )
            .order_by(
                SampleApplicationEvent.occurred_at,
                historical_application.first_seen_at,
                historical_application.id,
            )
            .limit(1)
        )
        value = await self._session.scalar(sent_assignment)
        if isinstance(value, str) and value.strip():
            return value
        value = await self._session.scalar(statement)
        return value if isinstance(value, str) and value.strip() else None

    async def load_compensation_bd_name(self) -> str | None:
        if self._request.creator_level is None:
            return None
        consumed = aliased(SampleApplicationEvent)
        opened = await self._session.scalar(
            select(SampleApplicationEvent)
            .where(
                SampleApplicationEvent.tenant_id == self._request.tenant_id,
                SampleApplicationEvent.shop_id == self._request.shop_id,
                SampleApplicationEvent.event_type == "bd_assignment_compensation_opened",
                SampleApplicationEvent.event_source == "erp_assignment_correction",
                SampleApplicationEvent.after_data["creator_level"].astext
                == self._request.creator_level,
                ~select(consumed.id)
                .where(
                    consumed.tenant_id == SampleApplicationEvent.tenant_id,
                    consumed.shop_id == SampleApplicationEvent.shop_id,
                    consumed.event_type == "bd_assignment_compensation_consumed",
                    consumed.event_source == "erp_assignment_correction",
                    consumed.external_event_id
                    == func.concat(SampleApplicationEvent.external_event_id, ":consumed"),
                )
                .exists(),
            )
            .order_by(SampleApplicationEvent.occurred_at, SampleApplicationEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if opened is None:
            return None
        bd_name = (opened.after_data or {}).get("bd_name")
        if not isinstance(bd_name, str) or not bd_name.strip():
            raise RuntimeError("Assignment compensation BD identity is invalid.")
        self._compensation_external_id = opened.external_event_id
        return bd_name.strip()

    async def load_workloads(
        self, roster: Sequence[BdWorkload]
    ) -> tuple[BdWorkload, ...]:
        return tuple(roster)

    async def record_decision(
        self,
        decision: AssignmentDecision,
        *,
        rule_version: str,
    ) -> None:
        now = datetime.now(UTC)
        before = {"assigned_bd_name": self._workflow.assigned_bd_name}
        after = {
            "sample_type": getattr(self._application, "sample_type", None) or "free",
            "assigned_bd_name": decision.assigned_bd_name,
            "assigned_bd_id": decision.assigned_bd_id,
            "creator_level": decision.creator_level,
            "decision_reason": decision.decision_reason,
            "blocked_reason": decision.blocked_reason,
            "rule_version": rule_version,
            "creator_gmv_minor": decision.creator_gmv_minor,
            "estimated_level_gmv_minor": decision.estimated_level_gmv_minor,
            "projected_gmv_spread_minor": decision.projected_gmv_spread_minor,
        }
        await self._session.execute(
            insert(SampleApplicationEvent)
            .values(
                tenant_id=self._request.tenant_id,
                shop_id=self._request.shop_id,
                sample_application_id=self._request.application_id,
                event_type=(
                    "bd_auto_assigned" if decision.assigned else "bd_auto_blocked"
                ),
                event_source="erp_auto_assignment",
                external_event_id=(
                    f"bd-auto:{rule_version}:{self._request.application_id}:"
                    f"{decision.assigned_bd_id or decision.blocked_reason}"
                ),
                actor_id="erp-auto-assignment",
                actor_name="ERP Auto Assignment",
                before_data=before,
                after_data=after,
                occurred_at=now,
            )
            .on_conflict_do_nothing(
                constraint="uq_sample_application_events_tenant_shop_source_external"
            )
        )
        if not decision.assigned:
            return
        if decision.decision_reason == "correction_compensation":
            if not self._compensation_external_id:
                raise RuntimeError("Assignment compensation source is unavailable.")
            consumed_id = await self._session.scalar(
                insert(SampleApplicationEvent)
                .values(
                    tenant_id=self._request.tenant_id,
                    shop_id=self._request.shop_id,
                    sample_application_id=self._request.application_id,
                    event_type="bd_assignment_compensation_consumed",
                    event_source="erp_assignment_correction",
                    external_event_id=f"{self._compensation_external_id}:consumed",
                    actor_id="erp-auto-assignment",
                    actor_name="ERP Auto Assignment",
                    before_data={},
                    after_data={"bd_name": decision.assigned_bd_name},
                    occurred_at=now,
                )
                .on_conflict_do_nothing(
                    constraint="uq_sample_application_events_tenant_shop_source_external"
                )
                .returning(SampleApplicationEvent.id)
            )
            if consumed_id is None:
                raise RuntimeError("Assignment compensation was already consumed.")
        if not self._workflow.feishu_record_id or not decision.recipient_open_id:
            raise RuntimeError(
                "Assigned sample is missing its Feishu delivery identity."
            )
        self._workflow.assigned_bd_name = decision.assigned_bd_name
        self._workflow.assignment_version += 1
        self._workflow.assigned_at = now
        self._workflow.processing_status = self._workflow.processing_status or "待处理"
        cancel, create = build_notification_outbox_statements(
            self._workflow,
            record_id=self._workflow.feishu_record_id,
            recipient_open_id=decision.recipient_open_id,
            event_id=f"bd-auto:{rule_version}:{self._request.application_id}",
            occurred_at=now,
            assignment_notice=(
                decision.decision_reason
                if decision.decision_reason
                in {
                    "same_creator_level_rotation_conflict",
                    "same_creator_level_imbalance",
                }
                else None
            ),
        )
        await self._session.execute(cancel)
        if create is not None:
            await self._session.execute(create)


def _creator_assignment_key(application: SampleApplication) -> str:
    username = (application.creator_username or "").strip().lstrip("@").casefold()
    if username:
        return f"username:{username}"
    creator_open_id = (application.creator_open_id or "").strip()
    if creator_open_id:
        return f"open:{creator_open_id}"
    return f"application:{application.platform_application_id}"
