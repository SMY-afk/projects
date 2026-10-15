from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FinancePeriodResponse(BaseModel):
    from_: datetime | None = Field(alias="from")
    to: datetime | None


class FinanceTrendPointResponse(BaseModel):
    date: datetime
    revenueAmountMinor: int
    refundAmountMinor: int
    feeAmountMinor: int
    settlementAmountMinor: int


class FinanceOverviewItemResponse(BaseModel):
    period: FinancePeriodResponse
    currency: str
    basis: str
    grossRevenueMinor: int
    refundAmountMinor: int
    platformFeeMinor: int
    affiliateCommissionMinor: int
    shippingAmountMinor: int
    taxAmountMinor: int
    adjustmentAmountMinor: int
    settlementAmountMinor: int
    paidAmountMinor: int
    outstandingAmountMinor: int
    statementTransactionDifferenceMinor: int
    paymentStatementDifferenceMinor: int
    contributionProfitMinor: int | None = None
    marginBps: int | None = None
    completeness: str
    missingReasons: list[str] = Field(default_factory=list)
    trend: list[FinanceTrendPointResponse] = Field(default_factory=list)


class FinanceOverviewResponse(BaseModel):
    items: list[FinanceOverviewItemResponse]


class FinanceComponentResponse(BaseModel):
    id: UUID
    componentCode: str
    componentCategory: str
    amountMinor: int
    currency: str
    platformSkuId: str | None
    orderLineId: UUID | None
    description: str | None


class FinanceTransactionResponse(BaseModel):
    id: UUID
    shopId: UUID
    platformTransactionId: str | None
    statementId: UUID | None
    platformStatementId: str | None
    orderId: UUID | None
    orderNumber: str | None
    orderPath: str | None
    platformOrderId: str | None
    type: str
    status: str
    basis: str
    currency: str
    revenueAmountMinor: int
    refundAmountMinor: int
    shippingAmountMinor: int
    feeAmountMinor: int
    adjustmentAmountMinor: int
    settlementAmountMinor: int
    expectedSettlementAmountMinor: int
    identityDifferenceMinor: int
    identityStatus: str
    occurredAt: datetime
    platformUpdatedAt: datetime | None
    syncedAt: datetime
    dataCompleteness: str
    components: list[FinanceComponentResponse] = Field(default_factory=list)


class FinanceTransactionListResponse(BaseModel):
    items: list[FinanceTransactionResponse]
    total: int
    page: int
    pageSize: int


class FinanceStatementResponse(BaseModel):
    id: UUID
    shopId: UUID
    platformStatementId: str
    status: str
    paymentStatus: str
    currency: str
    revenueAmountMinor: int
    feeAmountMinor: int
    adjustmentAmountMinor: int
    settlementAmountMinor: int
    expectedSettlementAmountMinor: int
    identityDifferenceMinor: int
    transactionCount: int
    transactionAmountMinor: int
    statementTransactionDifferenceMinor: int
    paymentCount: int
    paymentAmountMinor: int
    paymentStatementDifferenceMinor: int
    recexample81340158: str
    statementStartAt: datetime
    statementEndAt: datetime
    platformCreatedAt: datetime
    platformUpdatedAt: datetime | None
    syncedAt: datetime


class FinanceStatementListResponse(BaseModel):
    items: list[FinanceStatementResponse]
    total: int
    page: int
    pageSize: int


class LinkedFinancePaymentResponse(BaseModel):
    id: UUID
    platformPaymentId: str
    status: str
    currency: str
    paymentAmountMinor: int
    initiatedAt: datetime
    paidAt: datetime | None
    bankReferenceMasked: str | None


class FinanceStatementDetailResponse(FinanceStatementResponse):
    transactions: list[FinanceTransactionResponse] = Field(default_factory=list)
    payments: list[LinkedFinancePaymentResponse] = Field(default_factory=list)


class FinancePaymentResponse(LinkedFinancePaymentResponse):
    shopId: UUID
    statementCount: int
    statementAmountMinor: int
    differenceMinor: int
    recexample81340158: str
    platformUpdatedAt: datetime | None
    syncedAt: datetime


class FinancePaymentListResponse(BaseModel):
    items: list[FinancePaymentResponse]
    total: int
    page: int
    pageSize: int


class FinanceReconciliationItemResponse(BaseModel):
    kind: str
    entityType: str
    entityId: UUID
    reference: str
    currency: str
    expectedAmountMinor: int
    actualAmountMinor: int
    differenceMinor: int
    severity: str
    occurredAt: datetime


class FinanceReconciliationResponse(BaseModel):
    items: list[FinanceReconciliationItemResponse]
    total: int
    limit: int


class FinanceOrderCurrencySummaryResponse(BaseModel):
    currency: str
    transactionCount: int
    revenueAmountMinor: int
    feeAmountMinor: int
    settlementAmountMinor: int


class FinanceOrderSummaryResponse(BaseModel):
    orderId: UUID
    orderNumber: str
    platformOrderId: str
    totals: list[FinanceOrderCurrencySummaryResponse]
    transactions: list[FinanceTransactionResponse]


class FinanceSyncRequest(BaseModel):
    shopId: UUID
    mode: Literal["backfill", "incremental"] = "incremental"
    from_: datetime | None = None
    to: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_from_alias(cls, value):
        if isinstance(value, dict) and "from" in value and "from_" not in value:
            value = {**value, "from_": value["from"]}
        return value


class FinanceSyncResponse(BaseModel):
    runId: UUID
    shopId: UUID
    status: str
    fetchedCount: int
    writtenCount: int
    recoveryCursor: str | None
    error: str | None
