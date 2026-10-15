from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, case, or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_carrier import LogisticsCarrierService
from erp_api.models.logistics_platform_carrier_mapping import (
    LogisticsPlatformCarrierMapping,
)
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.platform_fulfillment_outbox import PlatformFulfillmentOutbox
from erp_api.models.shop import Shop
from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentCommand,
    PlatformFulfillmentError,
)


@dataclass(frozen=True)
class ClaimedFulfillment:
    event_id: UUID
    attempt_count: int


class PlatformFulfillmentOutboxRepository:
    def __init__(self, database: Database, tracking_cipher) -> None:
        self._database = database
        self._tracking_cipher = tracking_cipher

    async def claim(
        self, tenant_id: UUID, event_id: UUID, *, processing_timeout: timedelta
    ) -> ClaimedFulfillment | None:
        now = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            event = await session.get(
                PlatformFulfillmentOutbox, event_id, with_for_update=True
            )
            if event is None or event.status in {"succeeded", "skipped", "failed"}:
                return None
            if (
                event.status == "processing"
                and event.updated_at > now - processing_timeout
            ):
                return None
            if event.next_attempt_at and event.next_attempt_at > now:
                return None
            event.status = "processing"
            event.attempt_count += 1
            event.next_attempt_at = None
            await session.commit()
            return ClaimedFulfillment(event.id, event.attempt_count)
        return None

    async def load_command(
        self, tenant_id: UUID, event_id: UUID
    ) -> PlatformFulfillmentCommand:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(
                        PlatformFulfillmentOutbox,
                        LogisticsWaybill.tracking_number_ciphertext,
                        LogisticsWaybill.carrier_id,
                        LogisticsWaybill.service_id,
                        LogisticsCarrierService.configuration,
                        OrderFulfillment.delivery_option_id,
                    )
                    .join(
                        LogisticsWaybill,
                        LogisticsWaybill.id == PlatformFulfillmentOutbox.waybill_id,
                    )
                    .outerjoin(
                        LogisticsCarrierService,
                        LogisticsCarrierService.id == LogisticsWaybill.service_id,
                    )
                    .join(Shop, Shop.id == PlatformFulfillmentOutbox.shop_id)
                    .outerjoin(
                        OrderFulfillment,
                        and_(
                            OrderFulfillment.order_id
                            == PlatformFulfillmentOutbox.order_id,
                            OrderFulfillment.tenant_id
                            == PlatformFulfillmentOutbox.tenant_id,
                            OrderFulfillment.platform_package_id
                            == PlatformFulfillmentOutbox.platform_package_id,
                        ),
                    )
                    .where(PlatformFulfillmentOutbox.id == event_id)
                )
            ).one_or_none()
            if row is None:
                raise PlatformFulfillmentError(
                    "Platform fulfillment event was not found.",
                    code="fulfillment_event_not_found",
                    retryable=False,
                )
            (
                event,
                tracking_ciphertext,
                carrier_id,
                service_id,
                configuration,
                delivery_option_id,
            ) = row
            if not tracking_ciphertext or self._tracking_cipher is None:
                raise PlatformFulfillmentError(
                    "Waybill tracking number is unavailable.",
                    code="tracking_number_unavailable",
                    retryable=False,
                )
            provider_key = f"{event.platform}ShippingProviderId"
            provider_id = await session.scalar(
                select(LogisticsPlatformCarrierMapping.platform_carrier_id)
                .where(
                    LogisticsPlatformCarrierMapping.platform == event.platform,
                    LogisticsPlatformCarrierMapping.store_id == event.shop_id,
                    LogisticsPlatformCarrierMapping.carrier_id == carrier_id,
                    LogisticsPlatformCarrierMapping.status == "active",
                    or_(
                        LogisticsPlatformCarrierMapping.delivery_option_id
                        == delivery_option_id,
                        LogisticsPlatformCarrierMapping.delivery_option_id.is_(None),
                    ),
                    or_(
                        LogisticsPlatformCarrierMapping.service_id == service_id,
                        LogisticsPlatformCarrierMapping.service_id.is_(None),
                    ),
                )
                .order_by(
                    case(
                        (
                            LogisticsPlatformCarrierMapping.delivery_option_id
                            == delivery_option_id,
                            0,
                        ),
                        else_=1,
                    ),
                    case(
                        (
                            LogisticsPlatformCarrierMapping.service_id == service_id,
                            0,
                        ),
                        else_=1,
                    ),
                )
                .limit(1)
            )
            if provider_id is None:
                provider_id = (configuration or {}).get(provider_key)
            return PlatformFulfillmentCommand(
                event_id=event.id,
                tenant_id=tenant_id,
                shop_id=event.shop_id,
                platform=event.platform,
                platform_order_id=event.platform_order_id,
                platform_package_id=event.platform_package_id,
                tracking_number=self._tracking_cipher.decrypt(tracking_ciphertext),
                platform_carrier_id=(
                    str(provider_id).strip() if provider_id is not None else None
                ),
                shipped_at=event.created_at,
                idempotency_key=event.idempotency_key,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def succeed(
        self, tenant_id: UUID, event_id: UUID, platform_request_id: str | None
    ) -> None:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                PlatformFulfillmentOutbox, event_id, with_for_update=True
            )
            if event is None or event.status == "succeeded":
                return
            event.status = "succeeded"
            event.platform_request_id = platform_request_id
            event.last_error_code = None
            event.last_error_summary = None
            event.next_attempt_at = None
            event.completed_at = datetime.now(UTC)
            await session.commit()
            return

    async def fail(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        code: str,
        summary: str,
        retry_at: datetime | None,
    ) -> None:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                PlatformFulfillmentOutbox, event_id, with_for_update=True
            )
            if event is None or event.status == "succeeded":
                return
            event.status = "retry_wait" if retry_at else "failed"
            event.last_error_code = code[:64]
            event.last_error_summary = summary[:1000]
            event.next_attempt_at = retry_at
            event.completed_at = None if retry_at else datetime.now(UTC)
            await session.commit()
            return

    async def list_due(
        self, *, processing_timeout: timedelta, limit: int = 200
    ) -> list[tuple[UUID, UUID, int]]:
        now = datetime.now(UTC)
        async with self._database.system_session_factory() as session:
            rows = await session.execute(
                select(
                    PlatformFulfillmentOutbox.tenant_id,
                    PlatformFulfillmentOutbox.id,
                    PlatformFulfillmentOutbox.attempt_count,
                )
                .where(
                    or_(
                        PlatformFulfillmentOutbox.status == "pending",
                        (PlatformFulfillmentOutbox.status == "retry_wait")
                        & (PlatformFulfillmentOutbox.next_attempt_at <= now),
                        (PlatformFulfillmentOutbox.status == "processing")
                        & (
                            PlatformFulfillmentOutbox.updated_at
                            <= now - processing_timeout
                        ),
                    )
                )
                .order_by(PlatformFulfillmentOutbox.created_at)
                .limit(limit)
            )
            return [(row[0], row[1], row[2]) for row in rows]

    async def list_for_task(
        self, tenant_id: UUID, task_id: UUID
    ) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            events = await session.scalars(
                select(PlatformFulfillmentOutbox)
                .where(PlatformFulfillmentOutbox.task_id == task_id)
                .order_by(PlatformFulfillmentOutbox.created_at)
            )
            return [
                {
                    "id": event.id,
                    "taskId": event.task_id,
                    "packageId": event.package_id,
                    "waybillId": event.waybill_id,
                    "platform": event.platform,
                    "eventType": event.event_type,
                    "status": event.status,
                    "attemptCount": event.attempt_count,
                    "nextAttemptAt": event.next_attempt_at,
                    "lastErrorCode": event.last_error_code,
                    "platformRequestId": event.platform_request_id,
                    "completedAt": event.completed_at,
                    "createdAt": event.created_at,
                    "updatedAt": event.updated_at,
                }
                for event in events.all()
            ]
        return []
