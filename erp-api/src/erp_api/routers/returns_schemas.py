from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReturnsModuleResponse(BaseModel):
    module: Literal["returns"]
    status: Literal["registered"]


class ReturnRequestItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderLineId: UUID
    requestedQuantity: int = Field(ge=1)
    reasonCode: str = Field(min_length=1, max_length=64)
    note: str | None = Field(None, max_length=1000)


class ReturnRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    orderId: UUID
    requestType: Literal["return", "exchange"]
    reasonCode: str = Field(min_length=1, max_length=64)
    customerNote: str | None = Field(None, max_length=2000)
    items: list[ReturnRequestItemCreate] = Field(min_length=1, max_length=500)


class ReturnReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    versionId: int = Field(ge=1)
    note: str | None = Field(None, max_length=2000)


class ReturnEligibilityItemResponse(BaseModel):
    orderLineId: UUID
    sellerSku: str | None
    productName: str
    skuName: str | None
    orderedQuantity: int
    requestedQuantity: int
    availableQuantity: int


class ReturnEligibilityResponse(BaseModel):
    orderId: UUID
    orderNumber: str
    shopId: UUID
    items: list[ReturnEligibilityItemResponse]


class ReturnRequestItemResponse(BaseModel):
    id: UUID
    orderLineId: UUID
    platformReturnLineId: str | None = None
    sellerSku: str | None
    productName: str
    skuName: str | None
    requestedQuantity: int
    reasonCode: str
    note: str | None


class ReturnRmaResponse(BaseModel):
    id: UUID
    rmaNumber: str
    status: Literal["open", "in_transit", "received", "closed", "cancelled"]
    reverseTaskId: UUID | None
    generatedAt: datetime


class ReturnRequestResponse(BaseModel):
    id: UUID
    requestNumber: str
    orderId: UUID
    orderNumber: str
    shopId: UUID
    source: Literal["local", "platform"] = "local"
    platform: str | None = None
    platformReturnId: str | None = None
    platformStatus: str | None = None
    platformReasonText: str | None = None
    platformCreatedAt: datetime | None = None
    platformUpdatedAt: datetime | None = None
    refundCurrency: str | None = None
    refundAmountMinor: int | None = None
    requestType: Literal["return", "exchange", "refund"]
    status: Literal["pending_review", "approved", "rejected", "cancelled"]
    reasonCode: str
    customerNote: str | None
    createdByUserId: UUID | None
    reviewedByUserId: UUID | None
    reviewNote: str | None
    reviewedAt: datetime | None
    createdAt: datetime
    updatedAt: datetime
    versionId: int
    items: list[ReturnRequestItemResponse]
    rma: ReturnRmaResponse | None


class ReturnRequestListResponse(BaseModel):
    items: list[ReturnRequestResponse]
    total: int
    page: int
    pageSize: int


class ReturnSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shopId: UUID


class ReturnSyncResponse(BaseModel):
    shopId: UUID
    fetchedCount: int
    upsertedCount: int
    unmatchedOrderCount: int
    unmatchedLineCount: int
