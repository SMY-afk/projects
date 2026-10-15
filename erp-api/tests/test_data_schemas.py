from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from erp_api.services.data_schemas import (
    DataMetricValue,
    DataQueryContext,
    Money,
    UtcTimeRange,
)


def test_time_range_normalizes_offset_to_utc() -> None:
    context = DataQueryContext.model_validate(
        {
            "shop_timezone": "America/Los_Angeles",
            "range": {
                "from": "2026-08-01T00:00:00-07:00",
                "to": "2026-08-02T00:00:00-07:00",
            },
        }
    )

    assert context.range.from_ == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert context.range.to == datetime(2026, 8, 2, 7, tzinfo=UTC)


def test_time_range_rejects_naive_or_empty_values() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        UtcTimeRange.model_validate(
            {"from": "2026-08-01T00:00:00", "to": "2026-08-02T00:00:00Z"}
        )

    with pytest.raises(ValidationError, match="later than from"):
        UtcTimeRange(
            from_=datetime.now(UTC), to=datetime.now(UTC) - timedelta(seconds=1)
        )

    with pytest.raises(ValidationError, match="installed IANA timezone"):
        DataQueryContext.model_validate(
            {
                "shop_timezone": "Not/A-Timezone",
                "range": {"from": "2026-08-01T00:00:00Z", "to": "2026-08-02T00:00:00Z"},
            }
        )


def test_money_and_rate_keep_the_contract_precision() -> None:
    metric = DataMetricValue(
        metric="conversion_rate",
        value=Decimal("0.1234"),
        source_updated_at=datetime.now(UTC),
    )
    money = Money(amount_minor=12_345, currency="USD")

    assert metric.value == Decimal("0.1234")
    assert money.amount_minor == 12_345
    with pytest.raises(ValidationError):
        DataMetricValue(
            metric="conversion_rate",
            value=Decimal("0.12345"),
            source_updated_at=datetime.now(UTC),
        )
