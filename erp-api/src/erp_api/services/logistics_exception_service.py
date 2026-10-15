from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.logistics_exception_detection import detect_exception_candidates
from erp_api.services.logistics_exception_errors import (
    LogisticsExceptionValidationError,
)
from erp_api.services.logistics_exception_repository import LogisticsExceptionRepository


class LogisticsExceptionService:
    def __init__(
        self,
        repository: LogisticsExceptionRepository,
        *,
        pickup_timeout: timedelta,
        stalled_timeout: timedelta,
        platform_grace: timedelta,
    ) -> None:
        self.repository = repository
        self.pickup_timeout = pickup_timeout
        self.stalled_timeout = stalled_timeout
        self.platform_grace = platform_grace

    async def list_exceptions(self, tenant_id: UUID, **filters):
        return await self.repository.list_exceptions(tenant_id, **filters)

    async def get_exception(self, tenant_id: UUID, exception_id: UUID):
        return await self.repository.get_exception(tenant_id, exception_id)

    async def claim(self, tenant_id: UUID, exception_id: UUID, **values):
        return await self.repository.apply_action(
            tenant_id,
            exception_id,
            action_type="claimed",
            allowed_statuses={"open"},
            to_status="claimed",
            **values,
        )

    async def add_note(self, tenant_id: UUID, exception_id: UUID, **values):
        note = (values.get("note") or "").strip()
        if not note:
            raise LogisticsExceptionValidationError("Note is required.")
        values["note"] = note
        return await self.repository.apply_action(
            tenant_id,
            exception_id,
            action_type="note_added",
            allowed_statuses={"open", "claimed", "escalated", "resolved"},
            **values,
        )

    async def escalate(self, tenant_id: UUID, exception_id: UUID, **values):
        return await self.repository.apply_action(
            tenant_id,
            exception_id,
            action_type="escalated",
            allowed_statuses={"open", "claimed"},
            to_status="escalated",
            **values,
        )

    async def resolve(self, tenant_id: UUID, exception_id: UUID, **values):
        resolution = (values.get("resolution") or "").strip()
        if not resolution:
            raise LogisticsExceptionValidationError("Resolution is required.")
        values["resolution"] = resolution
        values["note"] = resolution
        return await self.repository.apply_action(
            tenant_id,
            exception_id,
            action_type="resolved",
            allowed_statuses={"claimed", "escalated"},
            to_status="resolved",
            **values,
        )

    async def close(self, tenant_id: UUID, exception_id: UUID, **values):
        return await self.repository.apply_action(
            tenant_id,
            exception_id,
            action_type="closed",
            allowed_statuses={"resolved"},
            to_status="closed",
            **values,
        )

    async def detect_tracking_event(self, tenant_id: UUID, event_id: UUID) -> int:
        context = await self.repository.context_for_event(tenant_id, event_id)
        return await self._detect_context(context, datetime.now(UTC), event_only=True)

    async def scan_all(self) -> dict[str, int]:
        return await self._scan(None)

    async def scan_tenant(self, tenant_id: UUID) -> dict[str, int]:
        return await self._scan(tenant_id)

    async def _scan(self, tenant_id: UUID | None) -> dict[str, int]:
        now = datetime.now(UTC)
        contexts = await self.repository.list_detection_contexts(tenant_id)
        detected = 0
        for context in contexts:
            detected += await self._detect_context(context, now)
        return {"scanned": len(contexts), "detected": detected}

    async def _detect_context(
        self, context, now: datetime, event_only: bool = False
    ) -> int:
        candidates = detect_exception_candidates(
            context.snapshot,
            now=now,
            pickup_timeout=self.pickup_timeout,
            stalled_timeout=self.stalled_timeout,
            platform_grace=self.platform_grace,
        )
        if event_only:
            candidates = [
                item for item in candidates if item.source == "tracking_event"
            ]
        created = 0
        for candidate in candidates:
            created += int(
                await self.repository.upsert_detection(
                    context, candidate, detected_at=now
                )
            )
        return created
