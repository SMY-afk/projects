from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.affiliate_creator_window_read import aggregate_creator_rows


def test_creator_daily_rows_sum_metrics_and_recompute_weighted_values() -> None:
    creator = SimpleNamespace(
        id=uuid4(), username="@creator", username_normalized="@creator"
    )
    canonical_creator = SimpleNamespace(
        id=uuid4(), username="@creator", username_normalized="creator"
    )
    first = SimpleNamespace(
        affiliate_gmv_minor=100,
        affiliate_order_count=1,
        items_sold=2,
        product_impressions=100,
        click_through_rate="0.1",
        affiliate_follower_count=100,
        average_affiliate_customers=Decimal("2.5"),
    )
    second = SimpleNamespace(
        affiliate_gmv_minor=500,
        affiliate_order_count=2,
        items_sold=3,
        product_impressions=300,
        click_through_rate="0.2",
        affiliate_follower_count=120,
        average_affiliate_customers=Decimal("3.5"),
    )
    captured = datetime(2026, 8, 28, tzinfo=UTC)

    rows = aggregate_creator_rows(
        [
            (creator, first, date(2026, 8, 1), captured),
            (canonical_creator, second, date(2026, 8, 2), captured),
        ]
    )

    assert len(rows) == 1
    _, metric = rows[0]
    assert metric.affiliate_gmv_minor == 600
    assert metric.affiliate_order_count == 3
    assert metric.items_sold == 5
    assert metric.product_impressions == 400
    assert metric.average_order_amount_minor == 200
    assert metric.click_through_rate == "0.175"
    assert metric.average_affiliate_customers == Decimal("6.0")
    assert metric.affiliate_follower_count == 120
