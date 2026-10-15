from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

EntityRoute = Literal["products", "creators", "videos", "lives"]
TimeSlot = Literal["1D", "7D", "30D"]
Currency = Literal["USD", "LOCAL"]
AuthorType = Literal["ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"]
BestsellerErrorCode = Literal[
    "data_unavailable",
    "reauthorization_required",
    "not_authorized",
    "rate_limited",
    "timeout",
    "platform_error",
    "sync_failed",
]


class BestsellerAuthorizationStatus(BaseModel):
    shopId: UUID
    status: Literal["ready", "reauthorization_required", "not_authorized"]
    requiredScopes: list[str]
    grantedScopes: list[str]
    missingScopes: list[str]
    canRead: bool


class BestsellerQueryResponse(BaseModel):
    shopId: UUID
    market: str | None
    date: date
    timeSlot: TimeSlot
    currency: Currency
    authorType: AuthorType | None


class BestsellerGmvResponse(BaseModel):
    raw: str
    currencyContext: Currency
    computable: Literal[False] = False


class BestsellerEntryResponse(BaseModel):
    entityType: Literal["product", "creator", "video", "live"]
    externalId: str
    rank: int
    displayName: str | None
    gmv: BestsellerGmvResponse
    extensions: dict[str, object]


class BestsellerFreshness(BaseModel):
    isStale: bool
    asOf: datetime | None = None
    lastErrorAt: datetime | None = None


class BestsellerReadError(BaseModel):
    code: BestsellerErrorCode
    message: str
    action: Literal["resync", "reauthorize"]


class BestsellerEnvelope[T](BaseModel):
    apiVersion: Literal["v1"] = "v1"
    source: Literal["local_connection", "local_snapshot", "queue"]
    data: T
    freshness: BestsellerFreshness
    errors: list[BestsellerReadError] = Field(default_factory=list)


class BestsellerListData(BaseModel):
    query: BestsellerQueryResponse
    items: list[BestsellerEntryResponse]


class BestsellerSyncRequest(BaseModel):
    shopId: UUID
    entityTypes: list[EntityRoute] = Field(min_length=1)
    date: date
    timeSlot: TimeSlot
    currency: Currency = "USD"
    authorType: AuthorType | None = None

    @model_validator(mode="after")
    def validate_author_type(self):
        if "creators" not in self.entityTypes and self.authorType is not None:
            raise ValueError("authorType is only valid when creators are requested")
        return self


class BestsellerSyncResponse(BaseModel):
    jobIds: list[str]
    alreadyQueued: list[str]
