from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_carrier import (
    LogisticsCarrier,
    LogisticsCarrierAccount,
    LogisticsCarrierService,
)
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.carrier_tracking_adapter import (
    CarrierTrackingUpdate,
    TrackingPollInput,
)
from erp_api.services.logistics_shipping_errors import LogisticsShippingNotFoundError
from erp_api.services.logistics_tracking_repository_helpers import (
    apply_waybill_tracking_status,
    tracking_dedupe_key,
    tracking_event_record,
    tracking_ignored_reason,
)
from erp_api.services.logistics_tracking_status import normalize_tracking_status
from erp_api.services.logistics_tracking_waybill_lookup import find_tracking_waybill
from erp_api.services.token_cipher import TokenCipher


@dataclass(frozen=True)
class CarrierTrackingTarget:
    carrier_id: UUID
    adapter_key: str


@dataclass(frozen=True)
class TrackingApplyResult:
    event_id: UUID
    duplicate: bool
    accepted: bool
    status: str | None
    ignored_reason: str | None


@dataclass(frozen=True)
class TrackingPollTarget:
    adapter_key: str
    context: TrackingPollInput


class LogisticsTrackingRepository:
    def __init__(self, database: Database, tracking_cipher: TokenCipher | None) -> None:
        self._database = database
        self._tracking_cipher = tracking_cipher

    async def resolve_carrier(
        self, tenant_id: UUID, carrier_code: str
    ) -> CarrierTrackingTarget:
        async for session in self._database.session(tenant_id):
            carrier = await session.scalar(
                select(LogisticsCarrier).where(
                    LogisticsCarrier.code == carrier_code.strip().upper(),
                    LogisticsCarrier.status == "active",
                )
            )
            if carrier is None:
                raise LogisticsShippingNotFoundError("Carrier was not found.")
            return CarrierTrackingTarget(carrier.id, carrier.adapter_key)
        raise RuntimeError("Tenant database session was not created.")

    async def apply_update(
        self,
        tenant_id: UUID,
        carrier_id: UUID,
        update: CarrierTrackingUpdate,
        *,
        source: str,
        payload_hash: str,
    ) -> TrackingApplyResult:
        dedupe_key = tracking_dedupe_key(update)
        async for session in self._database.session(tenant_id):
            waybill, configuration = await self._find_waybill(
                session, carrier_id, update
            )
            existing = await session.scalar(
                select(LogisticsTrackingEvent).where(
                    LogisticsTrackingEvent.waybill_id == waybill.id,
                    LogisticsTrackingEvent.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                return _duplicate_result(existing)
            normalized = normalize_tracking_status(update.raw_status, configuration)
            ignored_reason = tracking_ignored_reason(waybill, update, normalized)
            accepted = ignored_reason is None
            event = LogisticsTrackingEvent(
                tenant_id=tenant_id,
                waybill_id=waybill.id,
                carrier_id=carrier_id,
                source=source,
                external_event_id=update.external_event_id,
                dedupe_key=dedupe_key,
                raw_status=update.raw_status[:128],
                normalized_status=normalized,
                sequence_no=update.sequence_no,
                occurred_at=update.occurred_at,
                location=(update.location or "")[:500] or None,
                description=(update.description or "")[:2000] or None,
                payload_hash=payload_hash,
                accepted=accepted,
                ignored_reason=ignored_reason,
            )
            session.add(event)
            if accepted and normalized:
                await apply_waybill_tracking_status(
                    session, waybill, normalized, update
                )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(LogisticsTrackingEvent).where(
                        LogisticsTrackingEvent.waybill_id == waybill.id,
                        LogisticsTrackingEvent.dedupe_key == dedupe_key,
                    )
                )
                if existing is not None:
                    return _duplicate_result(existing)
                raise
            return TrackingApplyResult(
                event.id, False, accepted, normalized, ignored_reason
            )
        raise RuntimeError("Tenant database session was not created.")

    async def list_events(
        self, tenant_id: UUID, waybill_id: UUID
    ) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            events = await session.scalars(
                select(LogisticsTrackingEvent)
                .where(LogisticsTrackingEvent.waybill_id == waybill_id)
                .order_by(
                    LogisticsTrackingEvent.occurred_at,
                    LogisticsTrackingEvent.received_at,
                )
            )
            return [tracking_event_record(event) for event in events.all()]
        return []

    async def list_due_polls(self, *, limit: int = 200) -> list[tuple[UUID, UUID, int]]:
        now = datetime.now(UTC)
        async with self._database.system_session_factory() as session:
            rows = await session.execute(
                select(
                    LogisticsWaybill.tenant_id,
                    LogisticsWaybill.id,
                    LogisticsWaybill.tracking_poll_attempt_count,
                )
                .join(
                    LogisticsCarrier, LogisticsCarrier.id == LogisticsWaybill.carrier_id
                )
                .where(
                    LogisticsWaybill.is_current.is_(True),
                    LogisticsWaybill.status.in_({"shipped", "in_transit", "exception"}),
                    LogisticsCarrier.status == "active",
                    LogisticsCarrier.adapter_key != "manual",
                    or_(
                        LogisticsWaybill.tracking_next_poll_at.is_(None),
                        LogisticsWaybill.tracking_next_poll_at <= now,
                    ),
                )
                .order_by(LogisticsWaybill.tracking_next_poll_at.nullsfirst())
                .limit(limit)
            )
            return [(row[0], row[1], row[2]) for row in rows]

    async def load_poll_target(
        self, tenant_id: UUID, waybill_id: UUID
    ) -> TrackingPollTarget:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(
                        LogisticsWaybill,
                        LogisticsCarrier,
                        LogisticsCarrierService.configuration,
                        LogisticsCarrierAccount.secret_reference,
                    )
                    .join(
                        LogisticsCarrier,
                        LogisticsCarrier.id == LogisticsWaybill.carrier_id,
                    )
                    .outerjoin(
                        LogisticsCarrierService,
                        LogisticsCarrierService.id == LogisticsWaybill.service_id,
                    )
                    .outerjoin(
                        LogisticsCarrierAccount,
                        LogisticsCarrierAccount.id == LogisticsWaybill.account_id,
                    )
                    .where(LogisticsWaybill.id == waybill_id)
                )
            ).one_or_none()
            if row is None:
                raise LogisticsShippingNotFoundError("Waybill was not found.")
            waybill, carrier, configuration, secret_reference = row
            tracking_number = (
                self._tracking_cipher.decrypt(waybill.tracking_number_ciphertext)
                if self._tracking_cipher and waybill.tracking_number_ciphertext
                else None
            )
            return TrackingPollTarget(
                carrier.adapter_key,
                TrackingPollInput(
                    tenant_id,
                    waybill.id,
                    carrier.id,
                    waybill.external_waybill_id,
                    tracking_number,
                    configuration or {},
                    secret_reference,
                ),
            )
        raise RuntimeError("Tenant database session was not created.")

    async def finish_poll(
        self,
        tenant_id: UUID,
        waybill_id: UUID,
        *,
        interval: timedelta,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            waybill = await session.get(
                LogisticsWaybill, waybill_id, with_for_update=True
            )
            if waybill is None:
                return
            waybill.tracking_last_polled_at = now
            waybill.tracking_next_poll_at = now + interval
            waybill.tracking_poll_error_code = error_code
            waybill.tracking_poll_attempt_count += 1
            await session.commit()
            return

    async def _find_waybill(self, session, carrier_id, update):
        return await find_tracking_waybill(
            session, carrier_id, update, self._tracking_cipher
        )


def _duplicate_result(event):
    return TrackingApplyResult(
        event.id, True, event.accepted, event.normalized_status, event.ignored_reason
    )
