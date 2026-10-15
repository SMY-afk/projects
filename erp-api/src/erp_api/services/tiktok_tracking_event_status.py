"""Interpret actual tracking events without guessing status from numeric prefixes."""

import re

ACTION_NAMES = {
    "signed_personally": "delivered",
    "signed_others": "delivered",
    "pickup_success": "picked_up",
    "pickup_station_in": "in_transit",
    "sc_inbound": "in_transit",
    "sc_outbound": "in_transit",
    "pkg_shipped": "info_received",
    "pickup_start": "info_received",
}


def tracking_status(code, description, action_name=None):
    text = (description or "").upper()
    if any(
        word in text
        for word in (
            "DAMAGED",
            "LOST",
            "ADDRESS ERROR",
            "REFUSED",
            "NOT DELIVERED",
            "UNDELIVERED",
            "UNDELIVERABLE",
            "DELIVERY FAILED",
            "DELIVERY ATTEMPT",
        )
    ):
        return "exception"
    if "RETURN" in text:
        return "returned"
    if "CANCEL" in text:
        return "cancelled"
    if str(code) == "500901" or "PREPARED AT WAREHOUSE" in text:
        return "info_received"
    if action_name in ACTION_NAMES:
        return ACTION_NAMES[action_name]
    if "OUT FOR DELIVERY" in text:
        return "out_for_delivery"
    if re.search(r"\bDELIVERED\b", text) and not any(
        word in text
        for word in (
            "TO BE DELIVERED",
            "WILL BE DELIVERED",
            "DELIVERED TO CARRIER",
        )
    ):
        return "delivered"
    if "PICKED UP" in text or "COLLECTED BY" in text:
        return "picked_up"
    if any(
        word in text
        for word in ("IN TRANSIT", "ARRIVED AT", "DEPARTED", "CURRENTLY AT")
    ):
        return "in_transit"
    if not text and str(code) in {"50101", "50102"}:
        return "delivered"
    return "info_received"
