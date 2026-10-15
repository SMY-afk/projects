from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.shop import Shop
from erp_api.services.sample_type_policy import (
    sample_activation_condition,
    sample_assignment_condition,
)

_ROUTINE_REFRESH_INTERVAL = timedelta(days=1)
_SOURCE_EVENT_TYPES = (
    "tiktok_official_api",
    "tiktok_hubstudio_cdp",
    "tiktok_ziniao_cdp",
)
logger = logging.getLogger(__name__)


class SamplePostSourceWorkGate:
    """Use local PostgreSQL state before allowing any Feishu pipeline work."""

    def __init__(
        self,
        database,
        *,
        activation_at: datetime | None = None,
        cooperation_precheck=None,
        auto_assignments=None,
        notifications=None,
    ) -> None:
        if activation_at is not None and activation_at.utcoffset() is None:
            raise ValueError("Sample Feishu activation time must include a timezone.")
        self._database = database
        self._activation_at = activation_at.astimezone(UTC) if activation_at else None
        self._cooperation_precheck = cooperation_precheck
        self._auto_assignments = auto_assignments
        self._notifications = notifications

    async def has_work(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        source_type: str,
        source_results: tuple[object, ...],
        application_ids: frozenset[UUID] | None,
        obsolete_platform_application_ids: frozenset[str],
    ) -> bool:
        if source_type not in {"hubstudio_cdp", "official_api"} or not source_results:
            return self._decision(shop_id, source_type, "unknown_source", True)
        # Repeated grouped IDs are not new work; cleanup waits for another due
        # action or the daily refresh instead of rereading Feishu every cycle.
        if await self._has_missing_sample(tenant_id, shop_id, application_ids):
            return self._decision(shop_id, source_type, "missing_sample", True)
        if self._cooperation_precheck is not None and (
            await self._cooperation_precheck.has_pending(
                tenant_id,
                shop_id,
                application_ids=application_ids,
            )
        ):
            return self._decision(shop_id, source_type, "cooperation_due", True)
        if self._auto_assignments is not None and (
            await self._auto_assignments.has_pending(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=application_ids,
            )
        ):
            return self._decision(shop_id, source_type, "assignment_due", True)
        if self._notifications is not None and await self._notifications.list_due(
            tenant_id=tenant_id,
            shop_id=shop_id,
        ):
            return self._decision(shop_id, source_type, "notification_due", True)
        if not application_ids:
            return self._decision(shop_id, source_type, "empty_window", False)
        last_sync_at = await self._latest_feishu_sync_at(tenant_id, shop_id)
        if last_sync_at is None:
            return self._decision(shop_id, source_type, "first_sync", True)
        if await self._has_unsynced_status_change(
            tenant_id, shop_id, application_ids, since=last_sync_at
        ):
            return self._decision(shop_id, source_type, "status_changed", True)
        refresh_due = datetime.now(UTC) - last_sync_at >= _ROUTINE_REFRESH_INTERVAL
        return self._decision(
            shop_id,
            source_type,
            "routine_refresh" if refresh_due else "idle",
            refresh_due,
        )

    @staticmethod
    def _decision(shop_id: UUID, source_type: str, reason: str, allow: bool) -> bool:
        logger.info(
            "Sample Feishu work gate: %s (%s)",
            reason,
            source_type,
            extra={
                "event": "sample_feishu_work_gate",
                "shop_id": str(shop_id),
                "result": "allow" if allow else "skip",
            },
        )
        return allow

    async def _has_missing_sample(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: frozenset[UUID] | None,
    ) -> bool:
        if not application_ids:
            return False
        statement = (
            select(SampleApplication.id)
            .join(
                SampleApplicationWorkflow,
                and_(
                    SampleApplicationWorkflow.sample_application_id
                    == SampleApplication.id,
                    SampleApplicationWorkflow.tenant_id == SampleApplication.tenant_id,
                    SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
                ),
            )
            .join(
                SampleIngestBatch,
                and_(
                    SampleIngestBatch.id == SampleApplication.source_capture_id,
                    SampleIngestBatch.tenant_id == SampleApplication.tenant_id,
                    SampleIngestBatch.shop_id == SampleApplication.shop_id,
                ),
            )
            .join(
                Shop,
                and_(
                    Shop.id == SampleApplication.shop_id,
                    Shop.tenant_id == SampleApplication.tenant_id,
                ),
            )
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplication.id.in_(application_ids),
                SampleApplication.is_current_projection.is_(True),
                or_(
                    and_(SampleApplication.sample_type == "free",
                         SampleApplication.platform_status == "PENDING",
                         SampleApplication.is_approvable.is_(True)),
                    and_(SampleApplication.sample_type == "refundable", sample_assignment_condition()),
                ),
                SampleApplicationWorkflow.feishu_record_id.is_(None),
                SampleIngestBatch.status == "complete",
                SampleIngestBatch.finished_at.is_not(None),
            )
            .limit(1)
        )
        if self._activation_at is not None:
            statement = statement.where(sample_activation_condition(self._activation_at))
        async with self._database.system_session_factory() as session:
            return (await session.scalar(statement)) is not None

    async def _latest_feishu_sync_at(
        self, tenant_id: UUID, shop_id: UUID
    ) -> datetime | None:
        statement = select(func.max(SampleSyncRun.started_at)).where(
            SampleSyncRun.tenant_id == tenant_id,
            SampleSyncRun.shop_id == shop_id,
            SampleSyncRun.sync_type == "postgres_to_feishu",
            SampleSyncRun.status == "succeeded",
        )
        async with self._database.system_session_factory() as session:
            return await session.scalar(statement)

    async def _has_unsynced_status_change(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: frozenset[UUID],
        *,
        since: datetime,
    ) -> bool:
        statement = (
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.sample_application_id.in_(application_ids),
                SampleApplicationEvent.event_source.in_(_SOURCE_EVENT_TYPES),
                SampleApplicationEvent.event_type == "platform_status_changed",
                SampleApplicationEvent.occurred_at > since,
            )
            .limit(1)
        )
        async with self._database.system_session_factory() as session:
            return (await session.scalar(statement)) is not None
