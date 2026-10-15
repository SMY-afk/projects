from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from erp_api.services.tiktok_ads_order_schemas import TikTokAdsOrderSignal
from erp_api.services.tiktok_affiliate_order_schemas import TikTokAffiliateOrderSignal
from erp_api.services.tiktok_order_carriers import package_carrier
from erp_api.services.tiktok_order_parse_helpers import (
    _integer,
    _money,
    _optional_bool,
    _optional_text,
    _text,
    _timestamp,
)
from erp_api.services.tiktok_transport import TikTokApiError


@dataclass(frozen=True)
class TikTokOrderLine:
    platform_line_id: str
    platform_product_id: str | None
    platform_sku_id: str | None
    seller_sku: str | None
    product_name: str
    sku_name: str | None
    image_url: str | None
    quantity: int
    original_unit_price_minor: int
    sale_unit_price_minor: int
    discount_amount_minor: int
    line_total_amount_minor: int


@dataclass(frozen=True)
class TikTokFulfillment:
    platform_package_id: str
    delivery_option_id: str | None
    status: str
    carrier: str | None
    tracking_number: str | None
    shipped_at: datetime | None
    delivered_at: datetime | None


@dataclass(frozen=True)
class TikTokRecipient:
    name: str | None
    phone: str | None
    address: dict[str, str]
    country_code: str | None


@dataclass(frozen=True)
class TikTokOrderAttributionSignal:
    """Attribution fields confirmed by the step-0 order-detail mapping."""

    is_sample_order: bool | None = None
    source_updated_at: datetime | None = None

    @property
    def has_verified_signal(self) -> bool:
        """Whether the page contains the only currently verified signal field."""

        return self.is_sample_order is not None


@dataclass(frozen=True)
class TikTokOrder:
    platform_order_id: str
    order_number: str
    status: str
    external_status: str
    currency: str
    subtotal_amount_minor: int
    shipping_fee_minor: int
    discount_amount_minor: int
    tax_amount_minor: int
    total_amount_minor: int
    buyer_username: str | None
    placed_at: datetime
    paid_at: datetime | None
    platform_updated_at: datetime
    lines: list[TikTokOrderLine]
    fulfillments: list[TikTokFulfillment]
    recipient: TikTokRecipient | None
    attribution_signal: TikTokOrderAttributionSignal | None
    affiliate_signal: TikTokAffiliateOrderSignal | None = None
    ads_signal: TikTokAdsOrderSignal | None = None
    external_evidence_absence_reason: str | None = None
    shipping_type: str | None = None
    fulfillment_type: str | None = None


@dataclass(frozen=True)
class TikTokOrderPage:
    orders: list[TikTokOrder]
    next_page_token: str
    total_count: int | None


STATUS_MAP = {
    "UNPAID": "unpaid",
    "ON_HOLD": "on_hold",
    "AWAITING_SHIPMENT": "awaiting_shipment",
    "AWAITING_COLLECTION": "awaiting_collection",
    "PARTIALLY_SHIPPING": "partially_shipped",
    "PARTIALLY_SHIPPED": "partially_shipped",
    "IN_TRANSIT": "in_transit",
    "SHIPPED": "in_transit",
    "DELIVERED": "delivered",
    "COMPLETED": "completed",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
}


def parse_order_page_response(payload: Mapping[str, Any]) -> TikTokOrderPage:
    data = _data(payload)
    raw_orders = data.get("orders", [])
    if not isinstance(raw_orders, list):
        raise _invalid("TikTok order response did not contain an orders list.")
    token = data.get("next_page_token", "")
    if not isinstance(token, str):
        raise _invalid("TikTok order response contained an invalid page token.")
    return TikTokOrderPage(
        orders=[parse_order(item) for item in raw_orders],
        next_page_token=token,
        total_count=_integer(data.get("total_count")),
    )


def parse_order_detail_response(payload: Mapping[str, Any]) -> TikTokOrder:
    data = _data(payload)
    raw_orders = data.get("orders")
    if not isinstance(raw_orders, list) or len(raw_orders) != 1:
        raise _invalid(
            "TikTok order detail response did not contain exactly one order."
        )
    return parse_order(raw_orders[0])


def parse_order(value: Any) -> TikTokOrder:
    if not isinstance(value, Mapping):
        raise _invalid("TikTok order response contained an invalid order.")
    order_id = _text(value, "id", "order_id")
    external_status = _text(value, "status")
    placed_at = _timestamp(value.get("create_time"))
    updated_at = _timestamp(value.get("update_time"))
    if not order_id or not external_status or not placed_at or not updated_at:
        raise _invalid("TikTok order response missed an ID, status, or timestamp.")
    payment = value.get("payment") if isinstance(value.get("payment"), Mapping) else {}
    currency = (
        _text(payment, "currency") or _text(value, "currency") or "USD"
    ).upper()[:3]
    raw_lines = value.get("line_items", [])
    raw_packages = value.get("packages", [])
    if not isinstance(raw_lines, list) or not isinstance(raw_packages, list):
        raise _invalid(
            "TikTok order response contained invalid line items or packages."
        )
    recipient_value = value.get("recipient_address")
    return TikTokOrder(
        platform_order_id=order_id,
        order_number=_text(value, "order_number") or order_id,
        status=STATUS_MAP.get(external_status.upper(), "unknown"),
        external_status=external_status,
        currency=currency,
        subtotal_amount_minor=_money(
            payment, "sub_total", "subtotal", "original_total_product_price"
        ),
        shipping_fee_minor=_money(payment, "shipping_fee", "original_shipping_fee"),
        discount_amount_minor=_money(payment, "seller_discount")
        + _money(payment, "platform_discount"),
        tax_amount_minor=_money(payment, "tax", "tax_amount"),
        total_amount_minor=_money(payment, "total_amount", "total_payment"),
        buyer_username=_text(value, "buyer_username", "buyer_user_id"),
        placed_at=placed_at,
        paid_at=_timestamp(value.get("paid_time")),
        platform_updated_at=updated_at,
        lines=[_line(item) for item in raw_lines],
        fulfillments=[_fulfillment(item, raw_lines, value.get("shipping_provider"), len(raw_packages) == 1)
                      for item in raw_packages],
        recipient=_recipient(recipient_value)
        if isinstance(recipient_value, Mapping)
        else None,
        attribution_signal=_attribution_signal(value, source_updated_at=updated_at),
        shipping_type=_text(value, "shipping_type"),
        fulfillment_type=_text(value, "fulfillment_type"),
    )


def _line(value: Any) -> TikTokOrderLine:
    if not isinstance(value, Mapping):
        raise _invalid("TikTok order contained an invalid line item.")
    line_id = _text(value, "id", "line_item_id")
    if not line_id:
        raise _invalid("TikTok order line did not contain an ID.")
    image = value.get("sku_image")
    image_url = (
        _text(image, "url") if isinstance(image, Mapping) else _optional_text(image)
    )
    return TikTokOrderLine(
        platform_line_id=line_id,
        platform_product_id=_text(value, "product_id"),
        platform_sku_id=_text(value, "sku_id"),
        seller_sku=_text(value, "seller_sku"),
        product_name=_text(value, "product_name") or line_id,
        sku_name=_text(value, "sku_name"),
        image_url=image_url,
        quantity=max(1, _integer(value.get("quantity")) or 1),
        original_unit_price_minor=_money(
            value, "original_price", "original_unit_price"
        ),
        sale_unit_price_minor=_money(value, "sale_price", "sale_unit_price"),
        discount_amount_minor=_money(value, "seller_discount")
        + _money(value, "platform_discount"),
        line_total_amount_minor=_money(
            value, "display_price", "line_total", "total_amount"
        ),
    )


def _fulfillment(value: Any, lines, order_provider, single_package) -> TikTokFulfillment:
    if not isinstance(value, Mapping):
        raise _invalid("TikTok order contained an invalid package.")
    package_id = _text(value, "id", "package_id")
    if not package_id:
        raise _invalid("TikTok package did not contain an ID.")
    return TikTokFulfillment(
        platform_package_id=package_id,
        delivery_option_id=_text(value, "delivery_option_id"),
        status=_text(value, "status") or "unknown",
        carrier=package_carrier(value, lines, order_provider, single_package=single_package),
        tracking_number=_text(value, "tracking_number"),
        shipped_at=_timestamp(value.get("shipped_time")),
        delivered_at=_timestamp(value.get("delivery_time")),
    )


def _recipient(value: Mapping[str, Any]) -> TikTokRecipient:
    address = {
        str(key): str(item)
        for key, item in value.items()
        if item is not None and key not in {"name", "phone_number", "phone"}
    }
    return TikTokRecipient(
        name=_text(value, "name"),
        phone=_text(value, "phone_number", "phone"),
        address=address,
        country_code=_text(value, "region_code", "country_code"),
    )


def _attribution_signal(
    value: Mapping[str, Any], *, source_updated_at: datetime | None
) -> TikTokOrderAttributionSignal:
    """Parse only confirmed attribution fields without rejecting the order.

    The step-0 mapping confirms ``is_sample_order`` as a candidate signal and
    ``update_time`` as its source timestamp. Missing or invalid attribution
    fields become ``None``; core order validation remains separate.
    """

    return TikTokOrderAttributionSignal(
        is_sample_order=_optional_bool(value.get("is_sample_order")),
        source_updated_at=source_updated_at,
    )


def _data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise _invalid("TikTok order response was not an object.")
    data = payload.get("data", payload)
    return data if isinstance(data, Mapping) else {}


def _invalid(message: str) -> TikTokApiError:
    return TikTokApiError(message, code="invalid_order_response", status_code=502)
