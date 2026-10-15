from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.logistics_order_alerts import evaluate_alerts

NOW = datetime(2026, 10, 12, tzinfo=UTC)


def flags(status="AWAITING_SHIPMENT", hours=100, evidence=None):
    return evaluate_alerts(status, NOW - timedelta(hours=hours), NOW, evidence)


def test_strict_thresholds_and_elapsed_over_threshold():
    assert flags(hours=48) == {"unshipped_48h": 0, "uncollected_48h": 0}
    assert flags(hours=48 + 1 / 3600) == {"unshipped_48h": 1, "uncollected_48h": 1}
    assert flags(hours=77)["undelivered_77h"] == 0
    assert flags(hours=78)["undelivered_77h"] == 3600


@pytest.mark.parametrize(
    "status", ["UNPAID", "ON_HOLD", "CANCELLED", "DELIVERED", "COMPLETED"]
)
def test_invalid_or_finished_orders_are_excluded(status):
    assert flags(status) == {}


def test_overlapping_flags_and_real_collection_evidence():
    assert len(flags()) == 3
    assert flags("AWAITING_COLLECTION", 50) == {"uncollected_48h": 7200}
    assert flags("IN_TRANSIT") == {
        "uncollected_48h": 52 * 3600,
        "undelivered_77h": 23 * 3600,
    }
    assert flags(
        "AWAITING_COLLECTION", evidence={"firstLocationAt": NOW.isoformat()}
    ) == {"undelivered_77h": 23 * 3600}
    # Information received and order packed are not proof of physical pickup.
    assert "uncollected_48h" in flags(
        "AWAITING_COLLECTION", evidence={"trackingStatus": "info_received"}
    )
    assert "uncollected_48h" in flags(
        "AWAITING_COLLECTION", evidence={"trackingStatus": "ready_for_collection"}
    )


@pytest.mark.parametrize("status", ["AWAITING_COLLECTION", "IN_TRANSIT"])
@pytest.mark.parametrize("tracking_status", ["picked_up", "in_transit"])
def test_real_shipment_requires_first_specific_location(status, tracking_status):
    evidence = {
        "trackingStatus": tracking_status,
        "collectedAt": (NOW - timedelta(hours=30)).isoformat(),
    }
    assert flags(status, evidence=evidence)["uncollected_48h"] == 52 * 3600
    evidence["firstLocationAt"] = (NOW - timedelta(hours=20)).isoformat()
    # A first location after the deadline still finishes this warning node.
    assert "uncollected_48h" not in flags(status, evidence=evidence)
    assert "undelivered_77h" in flags(status, evidence=evidence)


def test_shipment_evidence_does_not_need_location_to_finish_unshipped_warning():
    evidence = {"collectedAt": (NOW - timedelta(hours=30)).isoformat()}
    assert set(flags(evidence=evidence)) == {"uncollected_48h", "undelivered_77h"}


def test_partial_shipping_remains_unfinished_even_if_known_package_delivered():
    evidence = {
        "deliveredAt": NOW.isoformat(),
        "firstLocationAt": NOW.isoformat(),
        "packages": [{"packageStatus": "DELIVERED"}],
    }
    assert set(flags("PARTIALLY_SHIPPING", evidence=evidence)) == {
        "unshipped_48h",
        "undelivered_77h",
    }
    evidence["packages"].append({"packageStatus": "IN_TRANSIT"})
    assert "undelivered_77h" in flags("IN_TRANSIT", evidence=evidence)


def test_future_order_timestamp_does_not_create_warning():
    assert flags(hours=-1) == {}


def test_single_package_real_delivery_finishes_node_even_if_package_status_lags():
    assert (
        flags(
            "IN_TRANSIT",
            evidence={
                "deliveredAt": NOW.isoformat(),
                "packages": [{"packageStatus": "FULFILLING"}],
            },
        )
        == {}
    )


@pytest.mark.asyncio
async def test_snapshot_deduplicates_overlap_and_uses_same_matches_and_shop_scope():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from sqlalchemy.dialects import postgresql

    from erp_api.services.logistics_order_alerts import warning_snapshot

    tenant, shop = uuid4(), uuid4()
    rows = [
        SimpleNamespace(
            id=uuid4(), external_status=status, placed_at=NOW - timedelta(hours=100)
        )
        for status in ["AWAITING_SHIPMENT", "IN_TRANSIT"]
    ]
    first = SimpleNamespace(all=lambda: rows)
    last = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [NOW - timedelta(minutes=1)])
    )
    session = SimpleNamespace(execute=AsyncMock(side_effect=[first, last]))
    matches, summary = await warning_snapshot(session, tenant, shop, None, None, NOW)
    assert summary["uniqueOrderCount"] == 2
    assert [card["overdueCount"] for card in summary["cards"]] == [1, 2, 2]
    assert sum(card["overdueCount"] for card in summary["cards"]) == 5
    for card in summary["cards"]:
        values = [
            value[card["key"]] for value in matches.values() if card["key"] in value
        ]
        assert card["overdueCount"] == len(values)
        assert card["longestOverdueSeconds"] == max(values)
    assert summary["lastDataSyncAt"] == NOW - timedelta(minutes=1)
    sql = str(
        session.execute.call_args_list[0]
        .args[0]
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert str(tenant) in sql and str(shop) in sql and "'active'" in sql
