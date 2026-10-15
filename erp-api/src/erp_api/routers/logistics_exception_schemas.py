from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ExceptionType = Literal[
    "not_picked_up",
    "stalled",
    "address_error",
    "refused",
    "lost",
    "damaged",
    "platform_status_mismatch",
]
ExceptionStatus = Literal["open", "claimed", "escalated", "resolved", "closed"]
ExceptionSeverity = Literal["low", "medium", "high", "critical"]


class ExceptionActionResponse(BaseModel):
    id: UUID
    actionType: str
    actorUserId: UUID | None
    fromStatus: str | None
    toStatus: str | None
    note: str | None
    details: dict[str, object]
    createdAt: datetime


class LogisticsExceptionResponse(BaseModel):
    id: UUID
    exceptionNumber: str
    waybillId: UUID
    packageId: UUID
    taskId: UUID
    taskNumber: str
    sourceNumber: str
    carrierName: str
    trackingNumberMasked: str | None
    exceptionType: ExceptionType
    status: ExceptionStatus
    severity: ExceptionSeverity
    source: Literal["tracking_event", "scheduled_scan"]
    title: str
    description: str
    assignedToUserId: UUID | None
    resolution: str | None
    firstDetectedAt: datetime
    lastDetectedAt: datetime
    occurrenceCount: int
    resolvedAt: datetime | None
    closedAt: datetime | None
    updatedAt: datetime
    versionId: int
    actions: list[ExceptionActionResponse]


class LogisticsExceptionListResponse(BaseModel):
    items: list[LogisticsExceptionResponse]
    total: int
    page: int
    pageSize: int


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versionId: int = Field(ge=1)


class NoteRequest(VersionRequest):
    note: str = Field(min_length=1, max_length=4000)


class EscalateRequest(NoteRequest):
    severity: Literal["high", "critical"]


class ResolveRequest(VersionRequest):
    resolution: str = Field(min_length=1, max_length=4000)


class CloseRequest(VersionRequest):
    note: str | None = Field(None, max_length=4000)


class DetectionRunResponse(BaseModel):
    scanned: int
    detected: int


class PlatformLogisticsSyncResponse(BaseModel):
    shopsScanned: int
    ordersScanned: int
    packagesSynced: int
    trackingEventsSynced: int
    failedOrders: int
    exceptionsScanned: int
    exceptionsDetected: int
