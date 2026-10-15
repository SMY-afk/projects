from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

Rate = Annotated[
    Decimal, Field(ge=Decimal(0), le=Decimal(1), max_digits=5, decimal_places=4)
]


class Money(BaseModel):
    """A monetary amount expressed in the smallest unit of its currency."""

    amount_minor: int
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class UtcTimeRange(BaseModel):
    """An inclusive-start, exclusive-end interval represented entirely in UTC."""

    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime

    @field_validator("from_", "to")
    @classmethod
    def require_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("to")
    @classmethod
    def require_non_empty_range(cls, value: datetime, info) -> datetime:
        start = info.data.get("from_")
        if start and value <= start:
            raise ValueError("to must be later than from")
        return value


class DataMetricValue(BaseModel):
    """A normalized data metric suitable for a tenant-scoped API response."""

    metric: str
    value: int | Money | Rate
    source_updated_at: datetime

    @field_validator("source_updated_at")
    @classmethod
    def require_utc_source_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_updated_at must include a UTC offset")
        return value.astimezone(UTC)


class DataQueryContext(BaseModel):
    """Time conversion metadata for the data API; not a browser-timezone contract."""

    shop_timezone: str
    range: UtcTimeRange

    @field_validator("shop_timezone")
    @classmethod
    def require_iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                "shop_timezone must be an installed IANA timezone"
            ) from error
        return value
