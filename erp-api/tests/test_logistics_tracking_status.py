from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from erp_api.services.carrier_tracking_adapter import CarrierTrackingUpdate
from erp_api.services.logistics_tracking_repository_helpers import (
    tracking_dedupe_key,
    tracking_ignored_reason,
)
from erp_api.services.logistics_tracking_status import (
    is_tracking_regression,
    normalize_tracking_status,
)


def test_maps_common_and_carrier_specific_statuses() -> None:
    assert normalize_tracking_status("out-for-delivery") == "out_for_delivery"
    assert normalize_tracking_status("SIGNED") == "delivered"
    assert (
        normalize_tracking_status(
            "custom-77", {"trackingStatusMap": {"CUSTOM_77": "exception"}}
        )
        == "exception"
    )
    assert normalize_tracking_status("not-known") is None


def test_terminal_and_same_timestamp_regressions_are_rejected() -> None:
    assert is_tracking_regression("delivered", "in_transit", same_timestamp=False)
    assert is_tracking_regression("out_for_delivery", "picked_up", same_timestamp=True)
    assert not is_tracking_regression(
        "out_for_delivery", "in_transit", same_timestamp=False
    )


def test_duplicate_and_out_of_order_guards() -> None:
    now = datetime.now(UTC)
    update = CarrierTrackingUpdate(
        "IN_TRANSIT", now, external_event_id="event-1", sequence_no=4
    )
    assert tracking_dedupe_key(update) == tracking_dedupe_key(update)
    waybill = SimpleNamespace(
        status="in_transit",
        tracking_status="in_transit",
        tracking_sequence=5,
        tracking_occurred_at=now,
    )
    assert tracking_ignored_reason(waybill, update, "in_transit") == (
        "out_of_order_sequence"
    )
    older = CarrierTrackingUpdate("PICKED_UP", now - timedelta(hours=1))
    waybill.tracking_sequence = None
    assert tracking_ignored_reason(waybill, older, "picked_up") == ("out_of_order_time")
