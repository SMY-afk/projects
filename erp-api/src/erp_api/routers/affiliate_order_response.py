from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.services.affiliate_content_form import affiliate_content_form_label


class AffiliateOrderItemResponse(BaseModel):
    mainOrderId: str
    creatorId: str | None
    creatorNickname: str | None
    campaignId: str | None
    productId: str
    productName: str | None
    skuId: str
    skuName: str | None
    orderCreatedAt: datetime
    promotionId: str | None
    promotionType: int | None
    contentForm: str | None
    contentFormLabel: str | None
    commissionBase: Decimal | None
    commissionCurrency: str | None
    commissionRate: Decimal | None
    estimatedStandardCommission: Decimal | None


def to_affiliate_order_item_response(
    item: AffiliateOrderItem,
) -> AffiliateOrderItemResponse:
    return AffiliateOrderItemResponse(
        mainOrderId=item.main_order_id,
        creatorId=item.creator_id,
        creatorNickname=item.creator_nickname,
        campaignId=item.campaign_id,
        productId=item.product_id,
        productName=item.product_name,
        skuId=item.sku_id,
        skuName=item.sku_name,
        orderCreatedAt=item.order_created_at,
        promotionId=item.promotion_id,
        promotionType=item.promotion_type,
        contentForm=item.content_form,
        contentFormLabel=affiliate_content_form_label(item.content_form),
        commissionBase=item.commission_base,
        commissionCurrency=item.commission_currency,
        commissionRate=item.commission_rate,
        estimatedStandardCommission=item.estimated_standard_commission,
    )
