"""Derive the user-approved milestones from chronological official events."""

import re
from itertools import pairwise

LOCATION_PATTERN = re.compile(
    r"\b(?:arrived at|departed(?: from)?|processed at|accepted at|currently at|"
    r"picked up at|received at)\s+(?:the\s+)?(.+?)(?:"
    r"\s+carrier['’]s facility|\s+(?:destination|origin|sorting) facility|[.;]|$)",
    re.IGNORECASE,
)
GENERIC_LOCATIONS = {
    "carrier",
    "carrier's facility",
    "facility",
    "next facility",
    "destination",
    "origin",
}


def module_tracking_status(event) -> str:
    # The user explicitly includes the displayed "Order placed" event in info_received.
    return {
        "10101": "info_received",
        "20101": "ready_for_collection",
        "21001": "info_received",
    }.get(str(event.action_code), event.normalized_status)


def first_location(description: str | None) -> str | None:
    match = LOCATION_PATTERN.search(description or "")
    if not match:
        return None
    location = match.group(1).strip(" .,")
    if not location or location.casefold() in GENERIC_LOCATIONS:
        return None
    if "carrier's facility" in location.casefold() or location.casefold().startswith(
        "next "
    ):
        return None
    return location


def derive_milestones(events, created_at):
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.sequence_no))
    shipped = next(
        (
            event
            for event in ordered
            if module_tracking_status(event) == "info_received"
        ),
        None,
    )
    located = next(
        (event for event in ordered if first_location(event.description)), None
    )
    delivered = next(
        (event for event in ordered if module_tracking_status(event) == "delivered"),
        None,
    )
    notes = []
    if shipped is None:
        notes.append("官方轨迹缺少已收到物流信息事件")
    if located is None:
        notes.append("官方轨迹未出现具体地点")
    if delivered is None:
        notes.append("官方轨迹暂无已送达事件")
    times = [
        created_at,
        *(
            event.occurred_at if event else None
            for event in [shipped, located, delivered]
        ),
    ]
    available = [value for value in times if value is not None]
    if any(end < start for start, end in pairwise(available)):
        notes.append("官方事件时间顺序异常，请核对原始轨迹")
    return {
        "orderCreatedAt": created_at,
        "shippedAt": shipped.occurred_at if shipped else None,
        "firstLocationAt": located.occurred_at if located else None,
        "deliveredAt": delivered.occurred_at if delivered else None,
        "shippedDescription": shipped.description if shipped else None,
        "firstLocationDescription": located.description if located else None,
        "deliveredDescription": delivered.description if delivered else None,
        "milestoneNotes": notes,
    }
