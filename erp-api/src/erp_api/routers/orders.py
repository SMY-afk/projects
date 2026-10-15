from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import ORDERS_BUYER_PII_VIEW, ORDERS_VIEW, SYNC_TRIGGER
from erp_api.models.order import Order
from erp_api.routers.affiliate_order_response import to_affiliate_order_item_response
from erp_api.routers.auth import (
    get_authenticated_user,
    require_permissions,
    require_session,
)
from erp_api.routers.order_attribution_response import (
    to_attribution_response,
    to_attribution_summary_response,
)
from erp_api.routers.order_response import (
    FulfillmentResponse,
    MaskedRecipientResponse,
    OrderLineResponse,
    OrderListResponse,
    OrderRecipientResponse,
    OrderResponse,
    OrderSyncResponse,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.order_repository import OrderRepository
from erp_api.services.order_sync_service import OrderSyncWindowError

router = APIRouter(prefix="/orders", tags=["orders"])

TrafficSource = Literal["organic", "paid_ads", "unknown"]
OperatorSubject = Literal["creator", "self_operated", "mall", "unknown"]
EntryPoint = Literal[
    "video",
    "live",
    "offsite",
    "showcase",
    "affiliate_product_page",
    "search_recommendation",
    "unknown",
]
SpecialOrderType = Literal["normal", "sample", "purchase_sample_rebate", "unknown"]
ClassificationStatus = Literal["confirmed", "derived", "unknown"]
ContentForm = Literal[
    "video",
    "live",
    "product_showcase",
    "affiliate_product_page",
    "external_traffic_plan",
]


def _repository(request: Request) -> OrderRepository:
    repository = request.app.state.order_repository
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.get("", response_model=OrderListResponse)
async def list_orders(
    request: Request,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(ORDERS_VIEW)),
    repository: OrderRepository = Depends(_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    shop_id: UUID | None = Query(None, alias="shopId"),
    keyword: str | None = Query(None),
    order_status: str | None = Query(None, alias="status"),
    updated_from: datetime | None = Query(None, alias="updatedFrom"),
    updated_to: datetime | None = Query(None, alias="updatedTo"),
    traffic_source: TrafficSource | None = Query(None, alias="trafficSource"),
    operator_subject: OperatorSubject | None = Query(None, alias="operatorSubject"),
    entry_point: EntryPoint | None = Query(None, alias="entryPoint"),
    special_order_type: SpecialOrderType | None = Query(None, alias="specialOrderType"),
    classification_status: ClassificationStatus | None = Query(
        None, alias="classificationStatus"
    ),
    content_form: ContentForm | None = Query(None, alias="contentForm"),
) -> OrderListResponse:
    result = await repository.list_orders(
        session.tenant_id,
        page=page,
        page_size=page_size,
        shop_id=shop_id,
        keyword=keyword,
        status=order_status,
        updated_from=updated_from,
        updated_to=updated_to,
        traffic_source=traffic_source,
        operator_subject=operator_subject,
        entry_point=entry_point,
        special_order_type=special_order_type,
        classification_status=classification_status,
        content_form=content_form,
    )
    return OrderListResponse(
        items=[
            _to_response(
                item.order,
                include_detail=False,
                settlement_amount_minor=item.settlement_amount_minor,
            )
            for item in result.items
        ],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.post("/sync", response_model=OrderSyncResponse)
async def sync_orders(
    request: Request,
    shop_id: UUID = Query(..., alias="shopId"),
    mode: str = Query("incremental", pattern="^(backfill|incremental)$"),
    updated_from: datetime | None = Query(None, alias="updatedFrom"),
    updated_to: datetime | None = Query(None, alias="updatedTo"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
) -> OrderSyncResponse:
    service = request.app.state.order_sync_service
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        result = await service.sync_orders(
            session.tenant_id,
            shop_id=shop_id,
            trigger="manual",
            mode=mode,
            updated_from=updated_from,
            updated_to=updated_to,
        )
    except OrderSyncWindowError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return OrderSyncResponse(
        runId=result.run_id,
        shopId=result.shop_id,
        status=result.status,
        fetchedCount=result.fetched_count,
        upsertedCount=result.upserted_count,
        confirmedCount=result.confirmed_count,
        derivedCount=result.derived_count,
        unknownCount=result.unknown_count,
        unsupportedFieldCount=result.unsupported_field_count,
        recoveryCursor=result.recovery_cursor,
        error=result.error,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(ORDERS_VIEW)),
    repository: OrderRepository = Depends(_repository),
) -> OrderResponse:
    result = await repository.get_order(session.tenant_id, order_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _to_response(result, include_detail=True)


@router.get("/{order_id}/recipient", response_model=OrderRecipientResponse)
async def get_order_recipient(
    order_id: UUID,
    request: Request,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(get_authenticated_user),
    repository: OrderRepository = Depends(_repository),
) -> OrderRecipientResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    allowed = ORDERS_BUYER_PII_VIEW in user.permissions
    order = await repository.get_order(session.tenant_id, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await repository.record_pii_access(
        session.tenant_id,
        order_id=order_id,
        actor_user_id=user.id,
        request_id=request_id,
        result="granted" if allowed else "denied",
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    recipient = await repository.reveal_recipient(session.tenant_id, order_id)
    if recipient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return OrderRecipientResponse(**recipient)


def _to_response(
    order: Order,
    *,
    include_detail: bool,
    settlement_amount_minor: int | None = None,
) -> OrderResponse:
    lines = order.lines if include_detail else []
    fulfillments = order.fulfillments if include_detail else []
    first_line = order.lines[0].product_name if order.lines else "-"
    item_count = sum(line.quantity for line in order.lines)
    shop = order.shop
    recipient = order.recipient
    return OrderResponse(
        id=order.id,
        shopId=order.shop_id,
        shopName=shop.shop_name if shop else "",
        platformName=shop.platform if shop else None,
        platformOrderId=order.platform_order_id,
        orderNumber=order.order_number,
        status=order.status,
        externalStatus=order.external_status,
        fulfillmentStatus="unallocated",
        warehouseNames=[],
        currency=order.currency,
        subtotalAmountMinor=order.subtotal_amount_minor,
        shippingFeeMinor=order.shipping_fee_minor,
        discountAmountMinor=order.discount_amount_minor,
        taxAmountMinor=order.tax_amount_minor,
        totalAmountMinor=order.total_amount_minor,
        settlementAmountMinor=settlement_amount_minor,
        buyerUsernameMasked=order.buyer_username_masked,
        itemSummary=f"{first_line} 等 {item_count} 件" if item_count else "暂无商品",
        itemCount=item_count,
        placedAt=order.placed_at,
        paidAt=order.paid_at,
        platformUpdatedAt=order.platform_updated_at,
        syncedAt=order.synced_at,
        lines=[
            OrderLineResponse(
                id=line.id,
                platformLineId=line.platform_line_id,
                platformProductId=line.platform_product_id,
                platformSkuId=line.platform_sku_id,
                sellerSku=line.seller_sku,
                productName=line.product_name,
                skuName=line.sku_name,
                imageUrl=line.image_url,
                quantity=line.quantity,
                originalUnitPriceMinor=line.original_unit_price_minor,
                saleUnitPriceMinor=line.sale_unit_price_minor,
                discountAmountMinor=line.discount_amount_minor,
                lineTotalAmountMinor=line.line_total_amount_minor,
            )
            for line in lines
        ],
        fulfillments=[
            FulfillmentResponse(
                id=item.id,
                platformPackageId=item.platform_package_id,
                status=item.status,
                carrier=item.carrier,
                trackingNumberMasked=item.tracking_number_masked,
                shippedAt=item.shipped_at,
                deliveredAt=item.delivered_at,
            )
            for item in fulfillments
        ],
        maskedRecipient=(
            MaskedRecipientResponse(
                name=recipient.name_masked,
                phone=recipient.phone_masked,
                address=recipient.address_masked,
                countryCode=recipient.country_code,
                purged=recipient.purged_at is not None,
            )
            if recipient and include_detail
            else None
        ),
        attribution=(
            to_attribution_response(order.attribution)
            if include_detail
            else to_attribution_summary_response(order.attribution)
        ),
        affiliateItems=[
            to_affiliate_order_item_response(item)
            for item in order.affiliate_order_items
        ],
    )
