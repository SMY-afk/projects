from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CarrierTrackingUpdate:
    raw_status: str
    occurred_at: datetime
    external_event_id: str | None = None
    external_waybill_id: str | None = None
    tracking_number: str | None = None
    sequence_no: int | None = None
    location: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TrackingPollInput:
    tenant_id: UUID
    waybill_id: UUID
    carrier_id: UUID
    external_waybill_id: str | None
    tracking_number: str | None
    service_configuration: dict[str, object]
    account_secret_reference: str | None


class CarrierTrackingAdapter(Protocol):
    key: str

    def verify_webhook(
        self, body: bytes, *, signature: str, timestamp: str, secret: str
    ) -> None: ...

    def parse_webhook(
        self, payload: dict[str, object], *, received_at: datetime
    ) -> list[CarrierTrackingUpdate]: ...

    async def poll_tracking(
        self, context: TrackingPollInput
    ) -> list[CarrierTrackingUpdate]: ...


class GenericCarrierTrackingAdapter:
    key = "manual"

    def verify_webhook(
        self, body: bytes, *, signature: str, timestamp: str, secret: str
    ) -> None:
        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            raise ValueError("Carrier webhook timestamp is invalid.") from None
        if abs(int(datetime.now(UTC).timestamp()) - timestamp_value) > 300:
            raise ValueError(
                "Carrier webhook timestamp is outside the accepted window."
            )
        expected = hmac.new(
            secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.removeprefix("sha256=")):
            raise ValueError("Carrier webhook signature is invalid.")

    def parse_webhook(
        self, payload: dict[str, object], *, received_at: datetime
    ) -> list[CarrierTrackingUpdate]:
        raw_events = payload.get("events")
        events = raw_events if isinstance(raw_events, list) else [payload]
        updates = [
            _parse_event(item, received_at) for item in events if isinstance(item, dict)
        ]
        if not updates:
            raise ValueError("Carrier webhook contains no tracking events.")
        return updates

    async def poll_tracking(
        self, context: TrackingPollInput
    ) -> list[CarrierTrackingUpdate]:
        del context
        return []


def _parse_event(
    data: dict[str, object], received_at: datetime
) -> CarrierTrackingUpdate:
    status = _text(data, "status", "statusCode", "trackingStatus")
    external_waybill_id = _text(data, "externalWaybillId", "waybillId")
    tracking_number = _text(data, "trackingNumber", "tracking_number")
    if not status or not (external_waybill_id or tracking_number):
        raise ValueError("Tracking status and waybill identity are required.")
    return CarrierTrackingUpdate(
        raw_status=status,
        occurred_at=_timestamp(data, received_at),
        external_event_id=_text(data, "eventId", "externalEventId", "id"),
        external_waybill_id=external_waybill_id,
        tracking_number=tracking_number,
        sequence_no=_integer(data, "sequence", "sequenceNumber"),
        location=_text(data, "location", "city"),
        description=_text(data, "description", "message"),
    )


def _text(data: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _integer(data: dict[str, object], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _timestamp(data: dict[str, object], fallback: datetime) -> datetime:
    value = next(
        (
            data.get(key)
            for key in ("occurredAt", "eventTime", "timestamp")
            if data.get(key)
        ),
        None,
    )
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            return (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
    except (OverflowError, TypeError, ValueError):
        pass
    return fallback
