from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4


def task_status(order_status: str) -> str:
    normalized = order_status.upper()
    if normalized in {"DELIVERED", "COMPLETED"}:
        return "delivered"
    if normalized == "IN_TRANSIT":
        return "in_transit"
    if normalized == "CANCELLED":
        return "cancelled"
    if normalized == "AWAITING_SHIPMENT":
        return "pending_dispatch"
    return "shipped"


def merge_task_status(current_status: str, order_status: str) -> str:
    desired = task_status(order_status)
    if desired in {"delivered", "cancelled"}:
        return desired
    if current_status in {"delivered", "cancelled", "exception"}:
        return current_status
    progress = {
        "pending_dispatch": 0,
        "shipped": 1,
        "in_transit": 2,
    }
    if current_status in progress and desired in progress:
        return max((current_status, desired), key=progress.__getitem__)
    return desired


def package_status(platform_status: str) -> str:
    if platform_status.upper() == "CANCELLED":
        return "cancelled"
    return "shipped"


def waybill_status(platform_status: str, order_status: str) -> str:
    normalized = platform_status.upper()
    if normalized == "CANCELLED":
        return "cancelled"
    if normalized in {"COMPLETED", "DELIVERED"}:
        return "delivered"
    return "in_transit" if order_status.upper() == "IN_TRANSIT" else "shipped"


def merge_waybill_status(
    current_status: str | None, platform_status: str, order_status: str
) -> str:
    desired = waybill_status(platform_status, order_status)
    if desired in {"delivered", "cancelled"}:
        return desired
    if current_status in {"delivered", "cancelled", "exception"}:
        return current_status
    return desired


def carrier_identity(detail) -> tuple[str, str]:
    if detail.carrier_name:
        name = detail.carrier_name.strip()
        code = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:64]
        return code or "TIKTOK_CARRIER", name[:128]
    return "TIKTOK_SHIPPING", "TikTok Shipping"


def package_number() -> str:
    return f"PKG-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"


def task_number() -> str:
    return f"LT-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"


def waybill_number() -> str:
    return f"WB-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"


def mask_tracking(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if len(stripped) <= 4:
        return "*" * len(stripped)
    return f"{stripped[:2]}{'*' * max(2, len(stripped) - 6)}{stripped[-4:]}"


def safe_mapping_payload(detail) -> dict[str, object]:
    return {
        "packageId": detail.package_id,
        "packageStatus": detail.package_status,
        "shippingProviderId": detail.platform_carrier_id,
        "shippingProviderName": detail.carrier_name,
        "deliveryOptionId": detail.delivery_option_id,
        "shippingType": detail.shipping_type,
        "syncedFrom": "get_package_detail",
    }
