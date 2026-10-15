from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

SyncType = Literal[
    "source_to_postgres",
    "postgres_to_feishu",
    "feishu_to_postgres",
    "reconciliation",
]
SourceType = Literal["official_api", "hubstudio_cdp", "postgresql", "feishu"]
RunStatus = Literal["queued", "running", "succeeded", "partial", "failed"]


class SampleSyncStatusResponse(BaseModel):
    runId: UUID
    shopId: UUID
    shopName: str
    syncType: SyncType
    sourceType: SourceType
    status: RunStatus
    pagesRead: int
    recordsRead: int
    recordsCreated: int
    recordsUpdated: int
    feishuCreated: int
    feishuUpdated: int
    errorCode: str | None
    startedAt: datetime
    finishedAt: datetime | None
    durationSeconds: int | None


class SampleSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shopId: UUID
    sourceType: Literal["official_api", "hubstudio_cdp"]
    mode: Literal["active", "terminal", "full"]


class SampleSyncPlanResponse(BaseModel):
    shopId: UUID
    shopName: str
    sourceType: Literal["official_api", "hubstudio_cdp"]
    mode: Literal["active", "terminal", "full"]
    dryRun: bool
    ready: bool
    reasonCode: str


class SampleSyncEnqueueResponse(BaseModel):
    jobId: str
    shopId: UUID
    shopName: str
    sourceType: Literal["official_api", "hubstudio_cdp"]
    mode: Literal["active", "terminal", "full"]
    status: Literal["queued"]


class SampleSyncMetricsResponse(BaseModel):
    shopId: UUID
    shopName: str
    syncType: SyncType
    sourceType: SourceType
    windowHours: int
    runCount: int
    queuedCount: int
    succeededCount: int
    partialCount: int
    failedCount: int
    runningCount: int
    recordsRead: int
    recordsCreated: int
    recordsUpdated: int
    feishuCreated: int
    feishuUpdated: int
    averageDurationSeconds: float | None
    lastSucceededAt: datetime | None
    lastFailedAt: datetime | None
