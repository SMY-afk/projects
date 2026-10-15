from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.carrier_tracking_adapter import CarrierTrackingUpdate
from erp_api.services.carrier_tracking_registry import CarrierTrackingAdapterRegistry
from erp_api.services.logistics_tracking_repository import (
    LogisticsTrackingRepository,
    TrackingApplyResult,
)

MAX_CARRIER_WEBHOOK_BYTES = 1_048_576
logger = logging.getLogger("erp_api.logistics_tracking")


class TrackingWebhookAuthenticationError(ValueError):
    pass


class TrackingWebhookPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class TrackingWebhookResult:
    received: int
    accepted: int
    duplicates: int
    ignored: int
    events: list[TrackingApplyResult]


class LogisticsTrackingService:
    def __init__(
        self,
        repository: LogisticsTrackingRepository,
        adapters: CarrierTrackingAdapterRegistry,
        *,
        webhook_secrets: dict[str, str],
        poll_interval: timedelta,
        poll_retry_interval: timedelta,
        exception_service=None,
    ) -> None:
        self.repository = repository
        self._adapters = adapters
        self._webhook_secrets = webhook_secrets
        self.poll_interval = poll_interval
        self.poll_retry_interval = poll_retry_interval
        self._exception_service = exception_service

    async def receive_webhook(
        self,
        tenant_id: UUID,
        carrier_code: str,
        body: bytes,
        *,
        signature: str,
        timestamp: str,
    ) -> TrackingWebhookResult:
        if len(body) > MAX_CARRIER_WEBHOOK_BYTES:
            raise TrackingWebhookPayloadError("Carrier webhook body is too large.")
        target = await self.repository.resolve_carrier(tenant_id, carrier_code)
        adapter = self._adapters.get(target.adapter_key)
        secret = self._secret(tenant_id, carrier_code, target.adapter_key)
        try:
            adapter.verify_webhook(
                body, signature=signature, timestamp=timestamp, secret=secret
            )
        except ValueError as error:
            raise TrackingWebhookAuthenticationError(str(error)) from error
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise TrackingWebhookPayloadError(
                "Carrier webhook JSON is invalid."
            ) from None
        if not isinstance(payload, dict):
            raise TrackingWebhookPayloadError(
                "Carrier webhook payload must be an object."
            )
        received_at = datetime.now(UTC)
        try:
            updates = adapter.parse_webhook(payload, received_at=received_at)
        except ValueError as error:
            raise TrackingWebhookPayloadError(str(error)) from error
        payload_hash = hashlib.sha256(body).hexdigest()
        results = [
            await self.repository.apply_update(
                tenant_id,
                target.carrier_id,
                update,
                source="webhook",
                payload_hash=payload_hash,
            )
            for update in updates
        ]
        await self._detect_exceptions(tenant_id, results)
        return TrackingWebhookResult(
            received=len(results),
            accepted=sum(item.accepted and not item.duplicate for item in results),
            duplicates=sum(item.duplicate for item in results),
            ignored=sum(not item.accepted and not item.duplicate for item in results),
            events=results,
        )

    async def poll(self, tenant_id: UUID, waybill_id: UUID) -> dict[str, int]:
        try:
            target = await self.repository.load_poll_target(tenant_id, waybill_id)
            updates = await self._adapters.get(target.adapter_key).poll_tracking(
                target.context
            )
            results = [
                await self.repository.apply_update(
                    tenant_id,
                    target.context.carrier_id,
                    update,
                    source="poll",
                    payload_hash=_poll_payload_hash(update),
                )
                for update in updates
            ]
            await self._detect_exceptions(tenant_id, results)
        except Exception as error:
            await self.repository.finish_poll(
                tenant_id,
                waybill_id,
                interval=self.poll_retry_interval,
                error_code=f"{type(error).__name__}"[:64],
            )
            raise
        await self.repository.finish_poll(
            tenant_id, waybill_id, interval=self.poll_interval
        )
        return {
            "received": len(results),
            "accepted": sum(item.accepted and not item.duplicate for item in results),
            "duplicates": sum(item.duplicate for item in results),
        }

    def _secret(self, tenant_id: UUID, carrier_code: str, adapter_key: str) -> str:
        secret = next(
            (
                self._webhook_secrets.get(key)
                for key in (
                    f"{tenant_id}:{carrier_code.upper()}",
                    carrier_code,
                    carrier_code.upper(),
                    carrier_code.lower(),
                    adapter_key,
                )
                if self._webhook_secrets.get(key)
            ),
            None,
        )
        if not secret:
            raise RuntimeError("Carrier webhook signing secret is not configured.")
        return secret

    async def _detect_exceptions(
        self, tenant_id: UUID, results: list[TrackingApplyResult]
    ) -> None:
        if self._exception_service is None:
            return
        for result in results:
            if result.duplicate or not result.accepted:
                continue
            try:
                await self._exception_service.detect_tracking_event(
                    tenant_id, result.event_id
                )
            except Exception:
                logger.exception(
                    "logistics_exception_detection_failed",
                    extra={
                        "event": "logistics_exception_detection_failed",
                        "tenant_id": str(tenant_id),
                        "tracking_event_id": str(result.event_id),
                    },
                )


def _poll_payload_hash(update: CarrierTrackingUpdate) -> str:
    value = "|".join(
        (
            update.external_event_id or "",
            update.raw_status,
            update.occurred_at.isoformat(),
            str(update.sequence_no or ""),
        )
    )
    return hashlib.sha256(value.encode()).hexdigest()
