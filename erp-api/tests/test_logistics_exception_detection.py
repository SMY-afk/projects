from datetime import UTC, datetime, timedelta

from erp_api.services.logistics_exception_detection import (
    DetectionSnapshot,
    detect_exception_candidates,
)


def _snapshot(**changes) -> DetectionSnapshot:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    values = {
        "waybill_id": "waybill-1",
        "waybill_status": "in_transit",
        "tracking_status": "in_transit",
        "waybill_updated_at": now - timedelta(hours=1),
        "tracking_occurred_at": now - timedelta(hours=1),
        "task_status": "in_transit",
        "order_status": "in_transit",
        "order_external_status": "IN_TRANSIT",
        "event_id": "event-1",
        "event_raw_status": "IN_TRANSIT",
        "event_description": "Parcel moving through network",
    }
    values.update(changes)
    return DetectionSnapshot(**values)


def test_detects_four_carrier_exception_categories_from_event_text() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    examples = {
        "Incorrect address supplied": "address_error",
        "Recipient refused delivery": "refused",
        "Parcel confirmed lost": "lost",
        "Package damaged in transit": "damaged",
    }

    for description, expected in examples.items():
        detected = detect_exception_candidates(
            _snapshot(event_raw_status="EXCEPTION", event_description=description),
            now=now,
            pickup_timeout=timedelta(hours=24),
            stalled_timeout=timedelta(hours=72),
            platform_grace=timedelta(hours=2),
        )
        assert expected in {item.exception_type for item in detected}


def test_detects_time_and_platform_mismatch_categories() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    detected = detect_exception_candidates(
        _snapshot(
            waybill_status="shipped",
            tracking_status="info_received",
            waybill_updated_at=now - timedelta(hours=30),
            task_status="shipped",
            order_status="awaiting_shipment",
            event_id=None,
            event_raw_status=None,
            event_description=None,
        ),
        now=now,
        pickup_timeout=timedelta(hours=24),
        stalled_timeout=timedelta(hours=72),
        platform_grace=timedelta(hours=2),
    )

    assert {item.exception_type for item in detected} == {
        "not_picked_up",
        "platform_status_mismatch",
    }


def test_detects_stalled_but_not_healthy_shipment() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    stale = detect_exception_candidates(
        _snapshot(tracking_occurred_at=now - timedelta(hours=80)),
        now=now,
        pickup_timeout=timedelta(hours=24),
        stalled_timeout=timedelta(hours=72),
        platform_grace=timedelta(hours=2),
    )
    healthy = detect_exception_candidates(
        _snapshot(),
        now=now,
        pickup_timeout=timedelta(hours=24),
        stalled_timeout=timedelta(hours=72),
        platform_grace=timedelta(hours=2),
    )

    assert {item.exception_type for item in stale} == {"stalled"}
    assert healthy == []


def test_detects_cancelled_package_while_platform_order_is_in_transit() -> None:
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    detected = detect_exception_candidates(
        _snapshot(
            waybill_status="cancelled",
            tracking_status="cancelled",
            waybill_updated_at=now - timedelta(hours=300),
            tracking_occurred_at=now - timedelta(hours=300),
            task_status="in_transit",
            order_status="in_transit",
            order_external_status="IN_TRANSIT",
            event_id=None,
            event_raw_status=None,
            event_description=None,
        ),
        now=now,
        pickup_timeout=timedelta(hours=24),
        stalled_timeout=timedelta(hours=72),
        platform_grace=timedelta(hours=2),
    )

    assert {item.exception_type for item in detected} == {"platform_status_mismatch"}
