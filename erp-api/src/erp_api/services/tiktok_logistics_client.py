from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

from erp_api.services.carrier_tracking_adapter import CarrierTrackingUpdate
from erp_api.services.tiktok_tracking_event_status import tracking_status
from erp_api.services.tiktok_transport import TikTokRequest, TikTokTransport


@dataclass(frozen=True)
class TikTokPackageDetail:
    package_id: str
    package_status: str
    platform_carrier_id: str | None
    carrier_name: str | None
    delivery_option_id: str | None
    shipping_type: str | None
    tracking_number: str | None
    order_line_item_ids: tuple[str, ...]
    updated_at: datetime | None
    weight_grams: int | None
    length_mm: int | None
    width_mm: int | None
    height_mm: int | None
    raw_payload: dict[str, object]


@dataclass(frozen=True)
class TikTokTrackingEvent:
    action_code: str
    normalized_status: str
    occurred_at: datetime
    description: str | None
    sequence_no: int
    payload_hash: str

    def as_update(
        self, *, external_waybill_id: str, tracking_number: str | None
    ) -> CarrierTrackingUpdate:
        return CarrierTrackingUpdate(
            raw_status=self.normalized_status,
            occurred_at=self.occurred_at,
            external_event_id=(
                f"tiktok:{external_waybill_id}:{self.action_code}:"
                f"{int(self.occurred_at.timestamp() * 1000)}:{self.sequence_no}"
            ),
            external_waybill_id=external_waybill_id,
            tracking_number=tracking_number,
            sequence_no=self.sequence_no,
            description=self.description,
        )


class TikTokLogisticsClient(Protocol):
    async def get_package_detail(
        self, access_token: str, *, shop_cipher: str, package_id: str
    ) -> TikTokPackageDetail: ...

    async def get_tracking(
        self, access_token: str, *, shop_cipher: str, order_id: str
    ) -> list[TikTokTrackingEvent]: ...


class HttpTikTokLogisticsClient:
    def __init__(self, transport: TikTokTransport) -> None:
        self._transport = transport

    async def get_package_detail(
        self, access_token: str, *, shop_cipher: str, package_id: str
    ) -> TikTokPackageDetail:
        payload = await self._transport.request(
            TikTokRequest(
                method="GET",
                path=f"/fulfillment/202309/packages/{package_id}",
                query={"shop_cipher": shop_cipher},
            ),
            access_token=access_token,
        )
        return parse_package_detail(payload)

    async def get_tracking(
        self, access_token: str, *, shop_cipher: str, order_id: str
    ) -> list[TikTokTrackingEvent]:
        payload = await self._transport.request(
            TikTokRequest(
                method="GET",
                path=f"/fulfillment/202309/orders/{order_id}/tracking",
                query={"shop_cipher": shop_cipher},
            ),
            access_token=access_token,
        )
        return parse_tracking_events(payload)


def parse_package_detail(payload: dict[str, object]) -> TikTokPackageDetail:
    data = _mapping(payload.get("data"))
    package_id = _text(data.get("package_id") or data.get("id"))
    if not package_id:
        raise ValueError("TikTok package detail did not contain a package ID.")
    dimensions = _mapping(data.get("dimension"))
    dimension_unit = _text(dimensions.get("unit"))
    weight = _mapping(data.get("weight"))
    return TikTokPackageDetail(
        package_id=package_id,
        package_status=_text(data.get("package_status") or data.get("status"))
        or "UNKNOWN",
        platform_carrier_id=_text(data.get("shipping_provider_id")),
        carrier_name=_text(data.get("shipping_provider_name")),
        delivery_option_id=_text(data.get("delivery_option_id")),
        shipping_type=_text(data.get("shipping_type")),
        tracking_number=_text(data.get("tracking_number")),
        order_line_item_ids=tuple(
            value
            for item in _list(data.get("order_line_item_ids"))
            if (value := _text(item))
        ),
        updated_at=_timestamp_seconds(data.get("update_time")),
        weight_grams=_weight_grams(weight.get("value"), _text(weight.get("unit"))),
        length_mm=_dimension_mm(dimensions.get("length"), dimension_unit),
        width_mm=_dimension_mm(dimensions.get("width"), dimension_unit),
        height_mm=_dimension_mm(dimensions.get("height"), dimension_unit),
        raw_payload=dict(data),
    )


def parse_tracking_events(payload: dict[str, object]) -> list[TikTokTrackingEvent]:
    data = _mapping(payload.get("data"))
    records = [item for item in _list(data.get("tracking")) if isinstance(item, dict)]
    records.sort(key=lambda item: _integer(item.get("update_time_millis")) or 0)
    events: list[TikTokTrackingEvent] = []
    for index, record in enumerate(records, start=1):
        occurred_at = _timestamp_millis(record.get("update_time_millis"))
        if occurred_at is None:
            continue
        action_code = _text(record.get("action_code")) or "unknown"
        description = _text(record.get("description"))
        canonical = {
            "action_code": action_code,
            "update_time_millis": _integer(record.get("update_time_millis")),
            "description": description,
        }
        events.append(
            TikTokTrackingEvent(
                action_code=action_code,
                normalized_status=tracking_status(
                    action_code, description, _text(record.get("action_code_name"))
                ),
                occurred_at=occurred_at,
                description=description,
                sequence_no=index,
                payload_hash=hashlib.sha256(
                    json.dumps(canonical, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
    return events


def _weight_grams(value: object, unit: str | None) -> int | None:
    factor = {
        "GRAM": Decimal(1),
        "KILOGRAM": Decimal(1000),
        "POUND": Decimal("453.59237"),
        "OUNCE": Decimal("28.349523125"),
    }.get((unit or "").upper())
    return _converted(value, factor)


def _dimension_mm(value: object, unit: str | None) -> int | None:
    factor = {
        "MILLIMETER": Decimal(1),
        "CENTIMETER": Decimal(10),
        "METER": Decimal(1000),
        "INCH": Decimal("25.4"),
    }.get((unit or "").upper())
    return _converted(value, factor)


def _converted(value: object, factor: Decimal | None) -> int | None:
    if value is None or factor is None:
        return None
    try:
        result = int(
            (Decimal(str(value)) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result > 0 else None


def _timestamp_seconds(value: object) -> datetime | None:
    integer = _integer(value)
    return datetime.fromtimestamp(integer, UTC) if integer is not None else None


def _timestamp_millis(value: object) -> datetime | None:
    integer = _integer(value)
    return datetime.fromtimestamp(integer / 1000, UTC) if integer is not None else None


def _integer(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []
