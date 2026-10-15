from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from erp_api.routers.affiliate_order_response import AffiliateOrderItemResponse
from erp_api.routers.order_attribution_response import (
    OrderAttributionResponse,
    OrderAttributionSummaryResponse,
)


class OrderLineResponse(BaseModel):
    id: UUID
    platformLineId: str
    platformProductId: str | None
    platformSkuId: str | None
    sellerSku: str | None
    productName: str
    skuName: str | None
    imageUrl: str | None
    quantity: int
    originalUnitPriceMinor: int
    saleUnitPriceMinor: int
    discountAmountMinor: int
    lineTotalAmountMinor: int


class FulfillmentResponse(BaseModel):
    id: UUID
    platformPackageId: str
    status: str
    carrier: str | None
    trackingNumberMasked: str | None
    shippedAt: datetime | None
    deliveredAt: datetime | None


class MaskedRecipientResponse(BaseModel):
    name: str | None
    phone: str | None
    address: str | None
    countryCode: str | None
    purged: bool


class OrderResponse(BaseModel):
    id: UUID
    shopId: UUID
    shopName: str
    platformName: str | None
    platformOrderId: str
    orderNumber: str
    status: str
    externalStatus: str
    fulfillmentStatus: str
    warehouseNames: list[str] = Field(default_factory=list)
    currency: str
    subtotalAmountMinor: int
    shippingFeeMinor: int
    discountAmountMinor: int
    taxAmountMinor: int
    totalAmountMinor: int
    settlementAmountMinor: int | None = None
    buyerUsernameMasked: str | None
    itemSummary: str
    itemCount: int
    placedAt: datetime
    paidAt: datetime | None
    platformUpdatedAt: datetime
    syncedAt: datetime
    lines: list[OrderLineResponse] = Field(default_factory=list)
    fulfillments: list[FulfillmentResponse] = Field(default_factory=list)
    maskedRecipient: MaskedRecipientResponse | None = None
    attribution: OrderAttributionResponse | OrderAttributionSummaryResponse | None = (
        None
    )
    affiliateItems: list[AffiliateOrderItemResponse] = Field(default_factory=list)


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    pageSize: int


class OrderRecipientResponse(BaseModel):
    name: str | None
    phone: str | None
    address: str | None
    countryCode: str | None
    purged: bool


class OrderSyncResponse(BaseModel):
    runId: UUID
    shopId: UUID
    status: str
    fetchedCount: int
    upsertedCount: int
    confirmedCount: int
    derivedCount: int
    unknownCount: int
    unsupportedFieldCount: int
    recoveryCursor: str | None
    error: str | None
