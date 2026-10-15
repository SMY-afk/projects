from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from erp_api.services.logistics_order_milestones import (
    derive_milestones,
    first_location,
)

CREATED = datetime(2026, 10, 7, 8, 52, 41, tzinfo=UTC)


def event(code, hours, description, status="in_transit"):
    return SimpleNamespace(
        action_code=code,
        occurred_at=CREATED + timedelta(hours=hours),
        sequence_no=1,
        normalized_status=status,
        description=description,
    )


def test_uses_the_user_screenshot_info_received_and_first_actual_place():
    events = [
        event("50102", 80, "Delivered, Front Desk", "delivered"),
        event("32501", 46, "In transit to the next facility."),
        event(
            "31201",
            46.12,
            "Arrived at the CITY OF INDUSTRY CA DISTRIBUTION CENTER carrier's facility.",
        ),
        event("21001", 1.04, "Package details received by the carrier.", "picked_up"),
        event("10101", 0, "Order placed.", "info_received"),
    ]
    result = derive_milestones(events, CREATED)
    assert result["orderCreatedAt"] == CREATED
    assert result["shippedAt"] == CREATED
    assert result["shippedDescription"] == "Order placed."
    assert result["firstLocationAt"] == CREATED + timedelta(hours=46.12)
    assert result["deliveredAt"] == CREATED + timedelta(hours=80)


def test_accepts_a_pickup_with_a_specific_city_and_ignores_generic_facilities():
    assert first_location("Package picked up and currently at CHINO.") == "CHINO"
    assert (
        first_location(
            "Departed the LOS ANGELES CA DISTRIBUTION CENTER carrier's facility."
        )
        == "LOS ANGELES CA DISTRIBUTION CENTER"
    )
    assert first_location("In transit to the next facility.") is None
    assert (
        first_location("Order packed and ready for dropoff at carrier's facility.")
        is None
    )
    assert first_location("Arrived at the carrier's facility.") is None


def test_missing_milestones_stay_empty_and_created_at_does_not_use_query_time():
    result = derive_milestones([], CREATED)
    assert result["orderCreatedAt"] == CREATED
    assert result["shippedAt"] is None
    assert result["firstLocationAt"] is None
    assert result["deliveredAt"] is None
    assert len(result["milestoneNotes"]) == 3
