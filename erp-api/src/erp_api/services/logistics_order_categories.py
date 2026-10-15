"""Official order categories and the delivered-only rolling calendar window."""

from calendar import monthrange
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_

from erp_api.models.order import Order

OrderCategory = Literal[
    "pending_shipment",
    "pending_collection",
    "partial_shipping",
    "in_transit",
    "delivered",
]
CATEGORY_STATUSES = {
    "pending_shipment": ("AWAITING_SHIPMENT",),
    "pending_collection": ("AWAITING_COLLECTION",),
    "partial_shipping": ("PARTIALLY_SHIPPING",),
    "in_transit": ("IN_TRANSIT",),
    "delivered": ("DELIVERED", "COMPLETED"),
}
MODULE_STATUSES = tuple(
    status for values in CATEGORY_STATUSES.values() for status in values
)


def delivered_since(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Shanghai"))
    index = local.year * 12 + local.month - 1 - 3
    year, month = divmod(index, 12)
    month += 1
    return local.replace(
        year=year, month=month, day=min(local.day, monthrange(year, month)[1])
    )


def category_condition(category: OrderCategory | None, since: datetime):
    if category == "delivered":
        return and_(
            Order.external_status.in_(CATEGORY_STATUSES[category]),
            Order.placed_at >= since,
        )
    if category:
        return Order.external_status.in_(CATEGORY_STATUSES[category])
    return or_(
        Order.external_status.in_(MODULE_STATUSES[:-2]),
        and_(
            Order.external_status.in_(CATEGORY_STATUSES["delivered"]),
            Order.placed_at >= since,
        ),
    )


def category_counts(status_counts: dict[str, int]) -> dict[str, int]:
    return {
        name: sum(status_counts.get(status, 0) for status in statuses)
        for name, statuses in CATEGORY_STATUSES.items()
    }
