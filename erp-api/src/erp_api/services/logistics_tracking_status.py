from __future__ import annotations

import re

NORMALIZED_TRACKING_STATUSES = {
    "info_received",
    "picked_up",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "exception",
    "returned",
    "cancelled",
}

STATUS_ALIASES = {
    "CREATED": "info_received",
    "LABEL_CREATED": "info_received",
    "PRE_TRANSIT": "info_received",
    "INFO_RECEIVED": "info_received",
    "ACCEPTED": "picked_up",
    "PICKED_UP": "picked_up",
    "PICKUP": "picked_up",
    "COLLECTED": "picked_up",
    "IN_TRANSIT": "in_transit",
    "TRANSIT": "in_transit",
    "DEPARTED": "in_transit",
    "ARRIVED": "in_transit",
    "OUT_FOR_DELIVERY": "out_for_delivery",
    "WITH_COURIER": "out_for_delivery",
    "DELIVERING": "out_for_delivery",
    "DELIVERED": "delivered",
    "SIGNED": "delivered",
    "EXCEPTION": "exception",
    "FAILED_ATTEMPT": "exception",
    "DELIVERY_FAILED": "exception",
    "HELD": "exception",
    "LOST": "exception",
    "DAMAGED": "exception",
    "RETURNED": "returned",
    "RETURN_TO_SENDER": "returned",
    "RTS": "returned",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}

STATUS_RANK = {
    "info_received": 10,
    "picked_up": 20,
    "in_transit": 30,
    "out_for_delivery": 40,
    "exception": 45,
    "delivered": 50,
    "returned": 50,
    "cancelled": 50,
}

TERMINAL_TRACKING_STATUSES = {"delivered", "returned", "cancelled"}


def normalize_tracking_status(
    raw_status: str, configuration: dict[str, object] | None = None
) -> str | None:
    key = _status_key(raw_status)
    custom = (configuration or {}).get("trackingStatusMap")
    if isinstance(custom, dict):
        mapped = next(
            (
                value
                for raw, value in custom.items()
                if _status_key(str(raw)) == key and isinstance(value, str)
            ),
            None,
        )
        if mapped in NORMALIZED_TRACKING_STATUSES:
            return mapped
    return STATUS_ALIASES.get(key)


def is_tracking_regression(
    current: str | None,
    incoming: str,
    *,
    same_timestamp: bool,
) -> bool:
    if current in TERMINAL_TRACKING_STATUSES and incoming != current:
        return True
    return bool(
        same_timestamp and current and STATUS_RANK[incoming] < STATUS_RANK[current]
    )


def _status_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")
