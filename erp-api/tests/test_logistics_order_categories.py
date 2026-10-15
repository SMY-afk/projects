from datetime import UTC, datetime

from sqlalchemy.dialects import postgresql

from erp_api.services.logistics_order_categories import (
    category_condition,
    category_counts,
    delivered_since,
)


def test_calendar_months_clamp_month_end_and_keep_shanghai_clock():
    result = delivered_since(datetime(2026, 5, 31, 10, tzinfo=UTC))
    assert result.isoformat() == "2026-02-28T18:00:00+08:00"


def test_only_delivered_category_has_creation_time_filter():
    since = datetime(2026, 7, 12, tzinfo=UTC)
    for name in (
        "pending_shipment",
        "pending_collection",
        "partial_shipping",
        "in_transit",
    ):
        sql = str(
            category_condition(name, since).compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "placed_at" not in sql
    sql = str(
        category_condition("delivered", since).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "placed_at" in sql and "COMPLETED" in sql


def test_completed_orders_are_counted_as_delivered_and_partial_shipping_is_separate():
    assert category_counts(
        {"COMPLETED": 3, "DELIVERED": 2, "PARTIALLY_SHIPPING": 1, "CANCELLED": 9}
    ) == {
        "pending_shipment": 0,
        "pending_collection": 0,
        "partial_shipping": 1,
        "in_transit": 0,
        "delivered": 5,
    }
