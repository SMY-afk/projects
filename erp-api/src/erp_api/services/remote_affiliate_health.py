"""Bounded, timestamped browser evidence from the local five-shop collector."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from erp_api.services.affiliate_capture_health import OBSERVATION_TTL_SECONDS

Resource = Literal["creators", "videos"]
State = Literal[
    "browser_offline", "connecting", "online", "session_expired", "captcha"
]


class DateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: Resource
    latest_available_date: date
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Direct observation must include a timezone")
        return value.astimezone(UTC)


class RemoteAffiliateHealthReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shop_id: UUID
    platform_shop_id: str = Field(min_length=1, max_length=64)
    state: State
    observed_at: datetime
    dates: list[DateEvidence] = Field(default_factory=list, max_length=2)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Browser observation must include a timezone")
        return value.astimezone(UTC)

    def validate_freshness(self, now: datetime) -> None:
        if not timedelta(0) <= now - self.observed_at <= timedelta(seconds=60):
            raise ValueError("Browser heartbeat is stale or in the future")
        if self.state != "online" and self.dates:
            raise ValueError("Offline browser cannot report direct dates")
        if len({item.resource for item in self.dates}) != len(self.dates):
            raise ValueError("Direct date resource is duplicated")
        for item in self.dates:
            if not timedelta(0) <= now - item.observed_at <= timedelta(
                seconds=OBSERVATION_TTL_SECONDS
            ):
                raise ValueError("Direct date observation is stale or in the future")
            if item.observed_at > self.observed_at:
                raise ValueError("Direct date observation is newer than the heartbeat")
