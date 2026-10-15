from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import ORDERS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.affiliate_content_form import affiliate_content_form_label
from erp_api.services.affiliate_repository import (
    AffiliateOrderPage,
    AffiliateOrderRecord,
    AffiliateRepository,
    CreatorStats,
    CreatorStatsPage,
)
from erp_api.services.auth import AuthSession, CurrentUser

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


class AffiliateOrderResponse(BaseModel):
    id: UUID
    shopId: UUID
    orderId: UUID | None
    orderNumber: str | None
    orderStatus: str | None
    mainOrderId: str
    creatorId: str | None
    creatorNickname: str | None
    campaignId: str | None
    productId: str
    productName: str | None
    imageUri: str | None
    skuId: str
    skuName: str | None
    orderCreatedAt: datetime
    isCod: bool | None
    isNonSameShopOrder: bool | None
    cosType: str | None
    promotionId: str | None
    promotionType: int | None
    contentForm: str | None
    contentFormLabel: str | None
    commissionBase: Decimal | None
    commissionCurrency: str | None
    commissionRate: Decimal | None
    estimatedStandardCommission: Decimal | None


class AffiliateOrderListResponse(BaseModel):
    items: list[AffiliateOrderResponse]
    total: int
    page: int
    pageSize: int


class AffiliateOrderDetailResponse(BaseModel):
    mainOrderId: str
    items: list[AffiliateOrderResponse]


class CreatorStatsResponse(BaseModel):
    creatorId: str
    creatorNickname: str | None
    commissionCurrency: str | None
    orderCount: int
    itemCount: int
    commissionBase: Decimal
    estimatedStandardCommission: Decimal
    lastOrderAt: datetime | None


class CreatorStatsListResponse(BaseModel):
    items: list[CreatorStatsResponse]
    total: int
    page: int
    pageSize: int


def _repository(request: Request) -> AffiliateRepository:
    repository = request.app.state.affiliate_repository
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.post("/ingest")
async def ingest_affiliate(payload: dict[str, Any]) -> dict[str, object]:
    data = payload.get("data") or {}
    sku_order_list = data.get("sku_order_list") or []
    return {
        "code": 0,
        "received": len(sku_order_list),
        "has_more": data.get("has_more", False),
        "next_cursor": data.get("next_cursor"),
    }


@router.get("/orders", response_model=AffiliateOrderListResponse)
async def list_affiliate_orders(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(ORDERS_VIEW)),
    repository: AffiliateRepository = Depends(_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    shop_id: UUID | None = Query(None, alias="shopId"),
    main_order_id: str | None = Query(None, alias="mainOrderId"),
    creator_id: str | None = Query(None, alias="creatorId"),
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
) -> AffiliateOrderListResponse:
    result: AffiliateOrderPage = await repository.list_orders(
        session.tenant_id,
        page=page,
        page_size=page_size,
        shop_id=shop_id,
        main_order_id=main_order_id,
        creator_id=creator_id,
        created_from=created_from,
        created_to=created_to,
    )
    return AffiliateOrderListResponse(
        items=[_to_order_response(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.get("/orders/{main_order_id}", response_model=AffiliateOrderDetailResponse)
async def get_affiliate_order(
    main_order_id: str,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(ORDERS_VIEW)),
    repository: AffiliateRepository = Depends(_repository),
    shop_id: UUID | None = Query(None, alias="shopId"),
) -> AffiliateOrderDetailResponse:
    items = await repository.get_order(
        session.tenant_id,
        main_order_id,
        shop_id=shop_id,
    )
    if not items:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return AffiliateOrderDetailResponse(
        mainOrderId=main_order_id,
        items=[_to_order_response(item) for item in items],
    )


@router.get("/creators/stats", response_model=CreatorStatsListResponse)
async def list_creator_stats(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(ORDERS_VIEW)),
    repository: AffiliateRepository = Depends(_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    shop_id: UUID | None = Query(None, alias="shopId"),
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
) -> CreatorStatsListResponse:
    result: CreatorStatsPage = await repository.list_creator_stats(
        session.tenant_id,
        page=page,
        page_size=page_size,
        shop_id=shop_id,
        created_from=created_from,
        created_to=created_to,
    )
    return CreatorStatsListResponse(
        items=[_to_creator_stats_response(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


def _to_order_response(record: AffiliateOrderRecord) -> AffiliateOrderResponse:
    item = record.item
    return AffiliateOrderResponse(
        id=item.id,
        shopId=item.shop_id,
        orderId=record.order_id,
        orderNumber=record.order_number,
        orderStatus=record.order_status,
        mainOrderId=item.main_order_id,
        creatorId=item.creator_id,
        creatorNickname=item.creator_nickname,
        campaignId=item.campaign_id,
        productId=item.product_id,
        productName=item.product_name,
        imageUri=item.image_uri,
        skuId=item.sku_id,
        skuName=item.sku_name,
        orderCreatedAt=item.order_created_at,
        isCod=item.is_cod,
        isNonSameShopOrder=item.is_non_same_shop_order,
        cosType=item.cos_type,
        promotionId=item.promotion_id,
        promotionType=item.promotion_type,
        contentForm=item.content_form,
        contentFormLabel=affiliate_content_form_label(item.content_form),
        commissionBase=item.commission_base,
        commissionCurrency=item.commission_currency,
        commissionRate=item.commission_rate,
        estimatedStandardCommission=item.estimated_standard_commission,
    )


def _to_creator_stats_response(item: CreatorStats) -> CreatorStatsResponse:
    return CreatorStatsResponse(
        creatorId=item.creator_id,
        creatorNickname=item.creator_nickname,
        commissionCurrency=item.commission_currency,
        orderCount=item.order_count,
        itemCount=item.item_count,
        commissionBase=item.commission_base,
        estimatedStandardCommission=item.estimated_standard_commission,
        lastOrderAt=item.last_order_at,
    )
