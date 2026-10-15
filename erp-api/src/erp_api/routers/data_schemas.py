from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class Freshness(BaseModel):
    isStale: bool
    asOf: datetime | None = None


class OperationalError(BaseModel):
    code: Literal["data_unavailable"]
    message: str
    action: Literal["resync"]


class V1Envelope[T](BaseModel):
    apiVersion: Literal["v1"] = "v1"
    source: Literal["local_snapshot", "local_detail", "local_sync", "queue"]
    data: T
    freshness: Freshness
    errors: list[OperationalError] = Field(default_factory=list)


class SnapshotResponse(BaseModel):
    metricSet: str
    granularity: str
    windowStart: datetime
    windowEnd: datetime
    currency: str
    metrics: dict[str, object]
    sourceUpdatedAt: datetime | None
    capturedAt: datetime


class ContentResponse(BaseModel):
    platformExternalId: str
    fields: dict[str, object]
    sourceStatus: str | None
    status: str | None
    sourceUpdatedAt: datetime | None
    observedAt: datetime


class ContentRangeResponse(BaseModel):
    windowStart: datetime
    windowEnd: datetime
    shopTimezone: str
    isPartial: bool
    latestAvailableDate: date | None = None


class VideoContentEnvelope(V1Envelope[list[ContentResponse]]):
    range: ContentRangeResponse


class SyncStatusResponse(BaseModel):
    runId: UUID
    resourceType: str
    status: str
    attemptCount: int
    fetchedCount: int
    persistedCount: int
    errorCategory: str | None
    errorSummary: str | None
    freshAt: datetime | None
    startedAt: datetime
    finishedAt: datetime | None


class AdminResyncRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    shop_id: UUID
    resource_types: list[Literal["video", "live"]] = Field(
        default_factory=lambda: ["video", "live"]
    )
    window_start: datetime | None = None
    window_end: datetime | None = None
    currency: Literal["USD", "LOCAL"] = "USD"
    account_type: Literal[
        "ALL",
        "OFFICIAL_ACCOUNTS",
        "MARKETING_ACCOUNTS",
        "AFFILIATE_ACCOUNTS",
    ] = "ALL"

    @model_validator(mode="after")
    def validate_explicit_window(self):
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("windowStart and windowEnd must be provided together")
        if self.window_start is not None and set(self.resource_types) != {"video"}:
            raise ValueError("explicit windows can resync only video data")
        return self


class AdminResyncResponse(BaseModel):
    jobIds: list[str]
    alreadyQueued: list[str]
