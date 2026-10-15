"""One authoritative rule for warning totals, filtering and sorting."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select

from erp_api.models.order import Order
from erp_api.models.order_sync import OrderSyncCursor
from erp_api.models.shop import Shop

OrderAlert = Literal["unshipped_48h", "uncollected_48h", "undelivered_77h"]
AlertPhase = Literal["upcoming", "overdue"]
THRESHOLDS = {"unshipped_48h": 48, "uncollected_48h": 48, "undelivered_77h": 77}
ACTIVE_STATUSES = (
    "AWAITING_SHIPMENT",
    "AWAITING_COLLECTION",
    "PARTIALLY_SHIPPING",
    "IN_TRANSIT",
)


def evaluate_alerts(status, created_at, now, evidence=None, *, lead_hours=3):
    evidence = evidence or {}
    if status not in ACTIVE_STATUSES:
        return {}
    age = now.timestamp() - created_at.timestamp()
    if age < 0:
        return {}
    packages = evidence.get("packages") or []
    delivered = (
        status != "PARTIALLY_SHIPPING"
        and bool(packages)
        and (
            bool(evidence.get("deliveredAt"))
            and len(packages) == 1
            or all(
                item.get("packageStatus") in {"DELIVERED", "COMPLETED"}
                for item in packages
            )
        )
    )
    shipped = (
        delivered
        or bool(evidence.get("shippedAt") or evidence.get("firstLocationAt") or evidence.get("collectedAt"))
        or status == "IN_TRANSIT"
    )
    # Only the first concrete location finishes the real-shipment warning.
    # Completed delivery also removes the order from unfinished-node warnings.
    real_shipped = delivered or bool(evidence.get("firstLocationAt"))
    incomplete = {
        "unshipped_48h": status == "PARTIALLY_SHIPPING"
        or (status == "AWAITING_SHIPMENT" and not shipped),
        "uncollected_48h": not real_shipped,
        "undelivered_77h": not delivered,
    }
    return {
        key: age - hours * 3600
        for key, hours in THRESHOLDS.items()
        if incomplete[key] and age >= (hours - lead_hours) * 3600
    }


def matches_phase(flags, key, phase):
    return key in flags and (flags[key] < 0 if phase == "upcoming" else flags[key] >= 0)


async def warning_snapshot(session, tenant, shop_id, order_number, realtime, now=None, *, lead_hours=3):
    now = now or datetime.now(UTC)
    filters = [
        Order.tenant_id == tenant,
        Shop.tenant_id == tenant,
        Shop.platform == "tiktok",
        Shop.status == "active",
        Order.external_status.in_(ACTIVE_STATUSES),
    ]
    if shop_id:
        filters.append(Order.shop_id == shop_id)
    if order_number:
        filters.append(Order.order_number == order_number)
    rows = (
        await session.execute(
            select(
                Order.id,
                Order.external_status,
                Order.placed_at,
                Order.platform_updated_at,
            )
            .join(Shop, Shop.id == Order.shop_id)
            .where(*filters)
        )
    ).all()
    cached = await realtime.cached(tenant, [row.id for row in rows]) if realtime else {}
    matches = {}
    for row in rows:
        flags = evaluate_alerts(
            row.external_status, row.placed_at, now, cached.get(row.id, {}), lead_hours=lead_hours
        )
        if flags:
            matches[row.id] = flags
    cards = []
    for key, hours in THRESHOLDS.items():
        overdue = [flags[key] for flags in matches.values() if matches_phase(flags, key, "overdue")]
        upcoming = [-flags[key] for flags in matches.values() if matches_phase(flags, key, "upcoming")]
        cards.append(
            {
                "key": key,
                "thresholdHours": hours,
                "upcomingCount": len(upcoming),
                "overdueCount": len(overdue),
                "closestRemainingSeconds": min(upcoming, default=0),
                "longestOverdueSeconds": max(overdue, default=0),
            }
        )
    shops = [
        Shop.tenant_id == tenant,
        Shop.platform == "tiktok",
        Shop.status == "active",
    ]
    if shop_id:
        shops.append(Shop.id == shop_id)
    times = (
        (
            await session.execute(
                select(OrderSyncCursor.last_success_at)
                .select_from(Shop)
                .outerjoin(
                    OrderSyncCursor,
                    (OrderSyncCursor.shop_id == Shop.id)
                    & (OrderSyncCursor.tenant_id == tenant),
                )
                .where(*shops)
            )
        )
        .scalars()
        .all()
    )
    synced_at = min(times) if times and all(times) else None
    return matches, {
        "cards": cards,
        "uniqueOrderCount": len(matches),
        "upcomingUniqueOrderCount": sum(any(value < 0 for value in flags.values()) for flags in matches.values()),
        "overdueUniqueOrderCount": sum(any(value >= 0 for value in flags.values()) for flags in matches.values()),
        "leadHours": lead_hours,
        "asOf": now,
        "lastDataSyncAt": synced_at,
    }
