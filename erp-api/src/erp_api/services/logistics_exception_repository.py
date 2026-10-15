from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_exception import (
    LogisticsException,
    LogisticsExceptionAction,
)
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.logistics_exception_detection import ExceptionCandidate
from erp_api.services.logistics_exception_errors import (
    LogisticsExceptionConflictError,
    LogisticsExceptionNotFoundError,
)
from erp_api.services.logistics_exception_queries import (
    DetectionContext,
    detection_query,
    exception_number,
    exception_record_query,
    latest_event_subquery,
    to_detection_context,
    to_exception_record,
)


@dataclass(frozen=True)
class ExceptionListResult:
    items: list[dict[str, object]]
    total: int


class LogisticsExceptionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_exceptions(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        exception_type: str | None,
        status: str | None,
        severity: str | None,
        assigned_to_user_id: UUID | None,
    ) -> ExceptionListResult:
        filters = []
        if exception_type:
            filters.append(LogisticsException.exception_type == exception_type)
        if status:
            filters.append(LogisticsException.status == status)
        if severity:
            filters.append(LogisticsException.severity == severity)
        if assigned_to_user_id:
            filters.append(
                LogisticsException.assigned_to_user_id == assigned_to_user_id
            )
        async for session in self._database.session(tenant_id):
            total = await session.scalar(
                select(func.count(LogisticsException.id)).where(*filters)
            )
            rows = await session.execute(
                exception_record_query()
                .where(*filters)
                .order_by(LogisticsException.last_detected_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return ExceptionListResult(
                [to_exception_record(row) for row in rows.all()], int(total or 0)
            )
        return ExceptionListResult([], 0)

    async def get_exception(
        self, tenant_id: UUID, exception_id: UUID
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    exception_record_query().where(
                        LogisticsException.id == exception_id
                    )
                )
            ).one_or_none()
            if row is None:
                raise LogisticsExceptionNotFoundError(
                    "Logistics exception was not found."
                )
            return to_exception_record(row)
        raise RuntimeError("Tenant database session was not created.")

    async def apply_action(
        self,
        tenant_id: UUID,
        exception_id: UUID,
        *,
        expected_version: int,
        actor_user_id: UUID,
        action_type: str,
        allowed_statuses: set[str],
        to_status: str | None = None,
        note: str | None = None,
        severity: str | None = None,
        resolution: str | None = None,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            exception = await session.scalar(
                select(LogisticsException)
                .where(LogisticsException.id == exception_id)
                .with_for_update()
            )
            if exception is None:
                raise LogisticsExceptionNotFoundError(
                    "Logistics exception was not found."
                )
            if exception.version_id != expected_version:
                raise LogisticsExceptionConflictError(
                    "Logistics exception was updated by another user."
                )
            if exception.status not in allowed_statuses:
                raise LogisticsExceptionConflictError(
                    f"Action '{action_type}' is not allowed from status '{exception.status}'."
                )
            previous = exception.status
            if to_status:
                exception.status = to_status
            if action_type == "claimed":
                exception.assigned_to_user_id = actor_user_id
            if severity:
                exception.severity = severity
            if resolution:
                exception.resolution = resolution
            if action_type == "resolved":
                exception.resolved_at = now
            if action_type == "closed":
                exception.closed_at = now
            exception.updated_at = now
            session.add(
                LogisticsExceptionAction(
                    tenant_id=tenant_id,
                    exception_id=exception.id,
                    action_type=action_type,
                    actor_user_id=actor_user_id,
                    from_status=previous,
                    to_status=exception.status,
                    note=note,
                    details={"severity": severity} if severity else {},
                )
            )
            await session.commit()
            return await self.get_exception(tenant_id, exception_id)
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_detection(
        self,
        context: DetectionContext,
        candidate: ExceptionCandidate,
        *,
        detected_at: datetime,
    ) -> bool:
        fingerprint = f"{context.waybill_id}:{candidate.exception_type}"
        async for session in self._database.session(context.tenant_id):
            existing = await session.scalar(
                select(LogisticsException)
                .where(
                    LogisticsException.fingerprint == fingerprint,
                    LogisticsException.status != "closed",
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.source_event_id == candidate.source_event_id:
                    return False
                existing.source_event_id = candidate.source_event_id
                existing.occurrence_count += 1
                existing.last_detected_at = detected_at
                existing.description = candidate.description[:4000]
                await session.commit()
                return False
            exception = LogisticsException(
                tenant_id=context.tenant_id,
                exception_number=exception_number(detected_at),
                waybill_id=context.waybill_id,
                package_id=context.package_id,
                task_id=context.task_id,
                source_event_id=candidate.source_event_id,
                exception_type=candidate.exception_type,
                severity=candidate.severity,
                source=candidate.source,
                fingerprint=fingerprint,
                title=candidate.title,
                description=candidate.description[:4000],
                first_detected_at=detected_at,
                last_detected_at=detected_at,
            )
            session.add(exception)
            await session.flush()
            session.add(
                LogisticsExceptionAction(
                    tenant_id=context.tenant_id,
                    exception_id=exception.id,
                    action_type="detected",
                    details={
                        "sourceEventId": str(candidate.source_event_id)
                        if candidate.source_event_id
                        else None
                    },
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True
        raise RuntimeError("Tenant database session was not created.")

    async def list_detection_contexts(
        self, tenant_id: UUID | None = None
    ) -> list[DetectionContext]:
        latest = latest_event_subquery()
        query = detection_query(latest).where(
            LogisticsWaybill.is_current.is_(True),
            LogisticsWaybill.status.in_(
                {"shipped", "in_transit", "exception", "delivered", "cancelled"}
            ),
        )
        if tenant_id is not None:
            async for session in self._database.session(tenant_id):
                rows = await session.execute(query)
                return [to_detection_context(row) for row in rows.all()]
            return []
        async with self._database.system_session_factory() as session:
            rows = await session.execute(query)
            return [to_detection_context(row) for row in rows.all()]

    async def context_for_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> DetectionContext:
        latest = latest_event_subquery(event_id)
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    detection_query(latest).where(latest.c.event_id == event_id)
                )
            ).one_or_none()
            if row is None:
                raise LogisticsExceptionNotFoundError("Tracking event was not found.")
            return to_detection_context(row)
        raise RuntimeError("Tenant database session was not created.")
