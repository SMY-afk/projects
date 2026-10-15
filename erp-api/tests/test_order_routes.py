from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.order import Order
from erp_api.models.order_attribution import OrderAttribution
from erp_api.models.shop import Shop
from erp_api.routers.orders import _to_response


def _order_with_attribution() -> Order:
    updated_at = datetime(2026, 8, 13, 2, 45, 49, tzinfo=UTC)
    order = Order(
        id=uuid4(),
        tenant_id=uuid4(),
        shop_id=uuid4(),
        platform_order_id="platform-order-1",
        order_number="order-1",
        status="completed",
        external_status="COMPLETED",
        currency="USD",
        subtotal_amount_minor=1250,
        shipping_fee_minor=250,
        discount_amount_minor=100,
        tax_amount_minor=125,
        total_amount_minor=1525,
        buyer_username_masked="b***",
        placed_at=updated_at,
        paid_at=updated_at,
        platform_updated_at=updated_at,
        synced_at=updated_at,
    )
    order.attribution = OrderAttribution(
        tenant_id=order.tenant_id,
        order_id=order.id,
        traffic_source="unknown",
        operator_subject="unknown",
        entry_point="unknown",
        special_order_type="unknown",
        chain_code="unknown",
        classification_status="unknown",
        classification_method="shop_order_detail",
        evidence_json={
            "source": "shop_order_detail",
            "field_path": "data.orders[].is_sample_order",
            "value": "false",
            "strength": "medium",
            "reason": "missing_platform_field",
        },
        source_updated_at=updated_at,
        source_hash="a" * 64,
    )
    return order


def _bind_shop(order: Order, *, platform: str = "tiktok") -> None:
    order.shop = Shop(
        id=order.shop_id,
        tenant_id=order.tenant_id,
        platform=platform,
        platform_shop_id="platform-shop-1",
        shop_name="Demo Shop",
        status="active",
    )


def test_order_response_maps_platform_from_loaded_shop_relation() -> None:
    order = _order_with_attribution()
    _bind_shop(order)

    response = _to_response(order, include_detail=False)

    assert response.platformName == "tiktok"


def test_order_response_allows_missing_shop_and_reserves_warehouse_fields() -> None:
    order = _order_with_attribution()
    order.shop = None  # type: ignore[assignment]

    response = _to_response(order, include_detail=False)

    assert response.platformName is None
    assert response.warehouseNames == []
    assert response.fulfillmentStatus == "unallocated"


def test_order_detail_maps_latest_attribution_relation_without_changing_order_facts() -> (
    None
):
    order = _order_with_attribution()

    response = _to_response(order, include_detail=True)

    assert response.attribution is not None
    assert response.attribution.chainCode == "unknown"
    assert response.attribution.classificationMethod == "shop_order_detail"
    assert response.attribution.sourceUpdatedAt == order.platform_updated_at
    assert (
        response.attribution.evidenceSummary[0].fieldPath
        == "data.orders[].is_sample_order"
    )
    assert response.totalAmountMinor == 1525
    assert response.status == "completed"
    assert response.buyerUsernameMasked == "b***"


def test_order_list_returns_only_attribution_summary() -> None:
    order = _order_with_attribution()
    order.attribution.creator_external_id = "creator-1"
    order.attribution.evidence_json["creator_handle"] = "pinky__shop4"
    order.attribution.evidence_json["creator_alias"] = "Pinky Shop"

    response = _to_response(order, include_detail=False)

    assert response.attribution is not None
    assert response.attribution.chainCode == "unknown"
    assert response.attribution.classificationStatus == "unknown"
    assert response.attribution.creatorExternalId == "creator-1"
    assert response.attribution.creatorHandle == "pinky__shop4"
    assert response.attribution.creatorAlias == "Pinky Shop"
    assert not hasattr(response.attribution, "classificationMethod")
    assert not hasattr(response.attribution, "evidenceSummary")


def test_order_list_response_includes_settlement_amount() -> None:
    response = _to_response(
        _order_with_attribution(),
        include_detail=False,
        settlement_amount_minor=1375,
    )

    assert response.settlementAmountMinor == 1375


def test_order_response_includes_all_matching_affiliate_sku_items() -> None:
    order = _order_with_attribution()
    order.affiliate_order_items = [
        AffiliateOrderItem(
            tenant_id=order.tenant_id,
            shop_id=order.shop_id,
            main_order_id=order.platform_order_id,
            creator_id="creator-1",
            creator_nickname="Creator One",
            product_id="product-1",
            product_name="Product One",
            sku_id="sku-1",
            order_created_at=order.placed_at,
            promotion_id="9371233970479993847",
            promotion_type=2,
            content_form="video",
            commission_base=Decimal("123.4000"),
            commission_currency="USD",
            commission_rate=Decimal("0.100000"),
            estimated_standard_commission=Decimal("12.3400"),
            raw_data={},
            source_record_key="source-1",
        ),
        AffiliateOrderItem(
            tenant_id=order.tenant_id,
            shop_id=order.shop_id,
            main_order_id=order.platform_order_id,
            creator_id="creator-1",
            creator_nickname="Creator One",
            product_id="product-2",
            sku_id="sku-2",
            order_created_at=order.placed_at,
            commission_rate=Decimal("0.150000"),
            estimated_standard_commission=Decimal("5.6700"),
            raw_data={},
            source_record_key="source-2",
        ),
    ]

    response = _to_response(order, include_detail=False)

    assert len(response.affiliateItems) == 2
    assert response.affiliateItems[0].mainOrderId == order.platform_order_id
    assert response.affiliateItems[0].creatorId == "creator-1"
    assert response.affiliateItems[0].productId == "product-1"
    assert response.affiliateItems[0].productName == "Product One"
    assert response.affiliateItems[0].skuId == "sku-1"
    assert response.affiliateItems[0].promotionId == "9371233970479993847"
    assert response.affiliateItems[0].commissionBase == Decimal("123.4000")
    assert response.affiliateItems[0].commissionCurrency == "USD"
    assert response.affiliateItems[0].commissionRate == Decimal("0.100000")
    assert response.affiliateItems[0].estimatedStandardCommission == Decimal("12.3400")
    assert response.affiliateItems[1].commissionRate == Decimal("0.150000")


def test_order_detail_without_attribution_returns_unknown_relation_object() -> None:
    order = _order_with_attribution()
    order.attribution = None

    response = _to_response(order, include_detail=True)

    assert response.attribution is not None
    assert response.attribution.trafficSource == "unknown"
    assert response.attribution.classificationStatus == "unknown"
    assert response.attribution.evidenceSummary == []


def test_order_detail_labels_missing_order_level_platform_evidence() -> None:
    order = _order_with_attribution()
    order.attribution.evidence_json = {
        "source": "external_order_evidence",
        "field_path": "affiliate_order|ads_order",
        "value": "missing_order_level_key",
        "strength": "unsupported",
        "reason": "platform_no_order_level_evidence",
    }

    response = _to_response(order, include_detail=True)

    assert response.attribution is not None
    evidence = response.attribution.evidenceSummary[0]
    assert evidence.reason == "platform_no_order_level_evidence"
    assert evidence.reasonLabel == "平台无订单级证据"


def test_order_detail_labels_missing_platform_source_field() -> None:
    response = _to_response(_order_with_attribution(), include_detail=True)

    assert response.attribution is not None
    assert (
        response.attribution.evidenceSummary[0].reasonLabel
        == "未识别：订单详情未返回来源字段"
    )


def test_order_detail_redacts_external_conversion_identifier() -> None:
    order = _order_with_attribution()
    order.attribution.evidence_json = {
        "source": "affiliate_order",
        "match_key_type": "order_id",
        "match_key": "platform-order-1",
        "external_conversion_id": "affiliate-conversion-secret",
        "strength": "strong",
        "reason": "exact_order_link",
    }

    response = _to_response(order, include_detail=True)

    evidence = response.attribution.evidenceSummary[0]  # type: ignore[union-attr]
    assert evidence.fieldPath == "affiliate_order.order_id"
    assert evidence.value.startswith("sha256:")
    assert "affiliate-conversion-secret" not in evidence.value
