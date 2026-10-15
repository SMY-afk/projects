from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LogisticsTaskItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceLineId: UUID
    plannedQuantity: int = Field(ge=1)


class LogisticsTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceType: Literal["sales_order"]
    sourceId: UUID
    items: list[LogisticsTaskItemCreate] = Field(min_length=1, max_length=500)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    note: str | None = Field(None, max_length=2000)


class LogisticsTaskPlanItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderLineId: UUID
    plannedQuantity: int = Field(ge=1)


class LogisticsTaskPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LogisticsTaskPlanItemCreate] = Field(min_length=1, max_length=500)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    note: str | None = Field(None, max_length=2000)


class LogisticsTasksGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderId: UUID
    tasks: list[LogisticsTaskPlanCreate] = Field(min_length=1, max_length=100)


class LogisticsTaskReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list["LogisticsTaskReviewItemRequest"] = Field(min_length=1, max_length=500)
    note: str | None = Field(None, max_length=2000)


class LogisticsTaskReviewItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskItemId: UUID
    actualQuantity: int = Field(ge=0)
    differenceReason: (
        Literal["shortage", "overage", "damaged", "wrong_sku", "other"] | None
    ) = None


class LogisticsPickingCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(None, max_length=2000)


class LogisticsScanResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=128)
    taskId: UUID | None = None


class LogisticsScanTaskMatch(BaseModel):
    taskId: UUID
    taskNumber: str
    sourceNumber: str
    status: str


class LogisticsScanItemMatch(LogisticsScanTaskMatch):
    taskItemId: UUID
    sellerSku: str | None
    platformSkuId: str | None
    productName: str
    skuName: str | None
    plannedQuantity: int


class LogisticsScanResolveResponse(BaseModel):
    code: str
    matchType: Literal["task", "task_item", "none"]
    tasks: list[LogisticsScanTaskMatch]
    items: list[LogisticsScanItemMatch]


class LogisticsTaskItemResponse(BaseModel):
    id: UUID
    sourceLineId: UUID
    orderLineId: UUID | None
    platformProductId: str | None
    platformSkuId: str | None
    sellerSku: str | None
    productName: str
    skuName: str | None
    plannedQuantity: int
    packedQuantity: int
    shippedQuantity: int


class LogisticsTaskOperationResponse(BaseModel):
    id: UUID
    operationType: str
    fromStatus: str | None
    toStatus: str | None
    actorUserId: UUID
    note: str | None
    details: dict[str, object]
    createdAt: datetime


class LogisticsTaskReviewResponse(BaseModel):
    id: UUID
    result: str
    expectedQuantity: int
    actualQuantity: int
    differences: list[dict[str, object]]
    note: str | None
    reviewerUserId: UUID
    reviewedAt: datetime


class LogisticsTaskResponse(BaseModel):
    id: UUID
    taskNumber: str
    sourceType: Literal["sales_order", "return", "exchange"]
    direction: Literal["forward", "reverse"]
    sourceId: UUID
    sourceNumber: str
    orderId: UUID | None
    rmaId: UUID | None
    shopId: UUID | None
    priority: Literal["low", "normal", "high", "urgent"]
    status: Literal[
        "pending_review",
        "pending_pack",
        "pending_waybill",
        "pending_dispatch",
        "shipped",
        "in_transit",
        "delivered",
        "exception",
        "cancelled",
    ]
    note: str | None
    createdByUserId: UUID
    createdAt: datetime
    updatedAt: datetime
    versionId: int
    items: list[LogisticsTaskItemResponse]
    operations: list[LogisticsTaskOperationResponse]
    reviews: list[LogisticsTaskReviewResponse]


class LogisticsTaskListResponse(BaseModel):
    items: list[LogisticsTaskResponse]
    total: int
    page: int
    pageSize: int


class LogisticsShopOptionResponse(BaseModel):
    id: UUID
    shopName: str
    platform: str
    platformShopId: str


class LogisticsTasksGenerateResponse(BaseModel):
    items: list[LogisticsTaskResponse]


class LogisticsMaskedRecipientResponse(BaseModel):
    name: str | None
    phone: str | None
    address: str | None
    countryCode: str | None
    purged: bool


class LogisticsOrderContextResponse(BaseModel):
    orderId: UUID
    orderNumber: str
    shopId: UUID
    shopName: str
    status: str
    externalStatus: str
    buyerUsernameMasked: str | None
    placedAt: datetime
    maskedRecipient: LogisticsMaskedRecipientResponse | None
