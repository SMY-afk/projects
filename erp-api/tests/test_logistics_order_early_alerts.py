from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.logistics_order_alerts import evaluate_alerts

NOW = datetime(2026, 10, 13, tzinfo=UTC)


@pytest.mark.parametrize("key,hours", [("unshipped_48h", 48), ("uncollected_48h", 48), ("undelivered_77h", 77)])
def test_early_window_and_deadline_boundaries(key, hours):
    created = NOW - timedelta(hours=hours)
    assert key not in evaluate_alerts("AWAITING_SHIPMENT", created, NOW - timedelta(hours=3, seconds=1))
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW - timedelta(hours=3))[key] == -10800
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW)[key] == 0
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW + timedelta(seconds=1))[key] == 1


def test_configurable_lead_and_delayed_scan_catches_overdue_directly():
    created = NOW - timedelta(hours=46)
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW, lead_hours=1) == {}
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW, lead_hours=4)["unshipped_48h"] == -7200
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW + timedelta(hours=5))["unshipped_48h"] == 10800
    # A restart can skip the entire upcoming interval; the current state must still be red.
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW + timedelta(days=10))["undelivered_77h"] > 0


def test_completed_nodes_exit_both_early_and_overdue_warnings():
    created = NOW - timedelta(hours=46)
    received = {"shippedAt": NOW.isoformat()}
    assert "unshipped_48h" not in evaluate_alerts("AWAITING_SHIPMENT", created, NOW, received)
    received["firstLocationAt"] = NOW.isoformat()
    assert evaluate_alerts("AWAITING_SHIPMENT", created, NOW, received) == {}
    assert evaluate_alerts("COMPLETED", created, NOW + timedelta(days=4), received) == {}


def test_timezone_offsets_do_not_change_deadline_age():
    created = NOW - timedelta(hours=46)
    from datetime import timezone

    same_instant = created.astimezone(timezone(timedelta(hours=-7)))
    assert evaluate_alerts("AWAITING_SHIPMENT", same_instant, NOW) == evaluate_alerts("AWAITING_SHIPMENT", created, NOW)


@pytest.mark.asyncio
async def test_snapshot_counts_both_phases_and_deduplicates_orders_across_nodes():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from erp_api.services.logistics_order_alerts import matches_phase, warning_snapshot

    rows = [SimpleNamespace(id=uuid4(), external_status=status, placed_at=NOW - timedelta(hours=age))
            for status, age in [("AWAITING_SHIPMENT", 46), ("IN_TRANSIT", 75), ("IN_TRANSIT", 100)]]
    session = SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(all=lambda: rows),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [NOW]))]))
    matches, summary = await warning_snapshot(session, uuid4(), None, None, None, NOW)
    assert summary["uniqueOrderCount"] == 3
    assert summary["upcomingUniqueOrderCount"] == summary["overdueUniqueOrderCount"] == 2
    assert [c["upcomingCount"] for c in summary["cards"]] == [1, 1, 1]
    assert [c["overdueCount"] for c in summary["cards"]] == [0, 2, 1]
    for card in summary["cards"]:
        for phase, count in [("upcoming", card["upcomingCount"]), ("overdue", card["overdueCount"])]:
            assert count == sum(matches_phase(flags, card["key"], phase) for flags in matches.values())
