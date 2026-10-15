from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from erp_api.services.affiliate_center_capture_policy import (
    sanitize_capture_payload,
)
from erp_api.services.sample_bd_assignment import classify_creator_level
from erp_api.services.sample_creator_profile import normalize_creator_profile
from erp_api.services.sample_type_policy import require_sample_type

STATUS_LABELS = {
    "REFUNDABLE_AWAITING_SHIPMENT": "买返待发货",
    "REFUNDABLE_SHIPPED": "买返已发货",
    "REFUNDABLE_CONTENT_PENDING": "买返处理中",
    "REFUNDABLE_REFUNDED": "买返已返款",
    "REFUNDABLE_NOT_REFUNDED": "买返未返款",
    "REFUNDABLE_CANCELLED": "买返已取消",
    "CANCELLED": "已取消",
    "PENDING": "待审核",
    "AWAITING_SHIPMENT": "待发货",
    "SHIPPED": "已发货",
    "CONTENT_PENDING": "处理中",
    "COMPLETED": "已完成",
    "OPS_COMPLETED": "已完成",
    "REJECT_CANCELLED": "已取消-审核拒绝",
    "OVERDUE_CANCELLED": "已取消-审核超时",
    "UNFULFILL_CANCELLED": "已取消-未履约",
    "DEL_OPEN_COLLAB": "已取消-合作计划删除",
    "SELLER_NOT_SHIP_CANCELLED": "已取消-商家未发货",
    "WITHDRAW_CANCELLED": "已取消-达人撤回",
    "UNFULFILLABLE_CANCELLED": "已取消-无法履约",
    "OPS_CANCELLED": "已取消-运营取消",
    "OPS_FAILED": "已取消-运营失败",
}

ACTIVE_SAMPLE_STATUSES = frozenset(
    {"PENDING", "AWAITING_SHIPMENT", "SHIPPED", "CONTENT_PENDING"}
)
TERMINAL_SAMPLE_STATUSES = (
    frozenset(STATUS_LABELS) - ACTIVE_SAMPLE_STATUSES - {"CANCELLED"}
)


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _preferred_integer(primary: Any, fallback: Any) -> int | None:
    value = _integer(primary)
    return value if value is not None else _integer(fallback)


def _group_products(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_items = payload.get("products")
    if not isinstance(raw_items, list):
        product = payload.get("product")
        return (product,) if isinstance(product, dict) else ()
    products = []
    for item in raw_items:
        product = item.get("product") if isinstance(item, dict) else None
        if isinstance(product, dict):
            products.append(product)
    return tuple(products)


def _joined_product_text(products: tuple[dict[str, Any], ...], key: str) -> str | None:
    values = []
    for product in products:
        value = _text(product.get(key))
        if value is not None and value not in values:
            values.append(value)
    return "、".join(values) or None


def _product_image_urls(products: tuple[dict[str, Any], ...]) -> list[str]:
    values = []
    for product in products:
        value = _text(product.get("sku_image_url"))
        if value is not None and value not in values:
            values.append(value)
    return values


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _money_minor(value: Any) -> int | None:
    amount = _decimal(str(value).replace(",", ""))
    if amount is None or amount < 0:
        return None
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _percentage_points(value: Any, *, basis_points: bool = False) -> Decimal | None:
    result = _decimal(value)
    if result is None or result < 0:
        return None
    return result / 100 if basis_points else result


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def normalize_sample_application(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
    source_type: str = "official_api",
) -> dict[str, Any]:
    if source_type not in {"official_api", "hubstudio_cdp"}:
        raise ValueError("Sample application source type is invalid.")
    sanitized = sanitize_capture_payload(payload)
    if not isinstance(sanitized, dict):
        raise TypeError("TikTok sample application payload is invalid.")
    payload = sanitized
    application_id = _text(payload.get("id"))
    status = _text(payload.get("status"))
    if not application_id or not status:
        raise ValueError("TikTok sample application is missing id or status.")
    creator = payload.get("creator")
    product = payload.get("product")
    if not isinstance(creator, dict) or not isinstance(product, dict):
        raise TypeError("TikTok sample application has invalid creator or product.")
    products = _group_products(payload)
    gmv = creator.get("gmv")
    performance = creator.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    performance_gmv = performance.get("gmv")
    if isinstance(performance_gmv, dict):
        gmv = performance_gmv
    gmv = gmv if isinstance(gmv, dict) else {}
    gmv_currency = _text(gmv.get("currency"))
    gmv_currency = gmv_currency.upper() if gmv_currency else None
    gmv_minor = _money_minor(gmv.get("amount"))
    creator_level = (
        classify_creator_level(gmv_minor)
        if gmv_minor is not None and gmv_currency == "USD"
        else None
    )
    normalized = {
        "sample_type": require_sample_type(payload.get("sample_type", "free")),
        "platform_application_id": application_id,
        "source_type": source_type,
        "platform_status": status,
        "creator_open_id": _text(creator.get("creator_open_id")),
        "creator_username": _text(creator.get("username")),
        "creator_nickname": _text(creator.get("nickname")),
        "follower_count": _integer(creator.get("follower_count")),
        "creator_gmv_minor": gmv_minor,
        "creator_gmv_currency": gmv_currency,
        "creator_level": creator_level,
        "creator_content_count": _preferred_integer(
            performance.get("ec_video_count"), creator.get("content_count")
        ),
        "creator_ec_video_view": _preferred_integer(
            performance.get("avg_ec_video_play_count"), creator.get("ec_video_view")
        ),
        "creator_fulfillment_percentage": _percentage_points(
            creator.get("fulfillment_percentage")
        )
        if creator.get("fulfillment_percentage") not in (None, "")
        else _percentage_points(performance.get("post_rate"), basis_points=True),
        "creator_units_sold": _integer(performance.get("units_sold")),
        "creator_pps": _decimal(performance.get("pps")),
        "creator_rating": _decimal(performance.get("rating")),
        "product_id": _joined_product_text(products, "id"),
        "product_title": _joined_product_text(products, "title"),
        "sku_id": _joined_product_text(products, "sku_id"),
        "sku_name": _joined_product_text(products, "sku_name"),
        "sku_image_url": _text(product.get("sku_image_url")),
        "product_image_urls": _product_image_urls(products),
        "is_current_projection": True,
        "order_id": _text(payload.get("order_id")),
        "tracking_number": _text(payload.get("tracking_number")),
        "commission_rate": _decimal(payload.get("commission_rate")),
        "available_quantity": _integer(payload.get("available_quantity")),
        "is_approvable": payload.get("is_approvable")
        if isinstance(payload.get("is_approvable"), bool)
        else None,
        "tiktok_applied_at": (
            _timestamp(payload.get("application_time"))
            if source_type == "hubstudio_cdp"
            else None
        ),
        "approve_expiration_at": _timestamp(payload.get("approve_expiration_time")),
        "shipment_expiration_at": _timestamp(payload.get("shipment_expiration_time")),
        "raw_payload": payload,
        "source_observed_at": observed_at.astimezone(UTC),
    }
    normalized.update(
        normalize_creator_profile(
            creator,
            observed_at=observed_at,
            source_type=source_type,
        )
    )
    if normalized["sample_type"] == "refundable" and isinstance(creator.get("verified_profile_snapshot"), dict):
        profile_time = datetime.fromisoformat(creator["verified_profile_observed_at"])
        if profile_time.tzinfo is None:
            raise ValueError("Refundable profile timestamp is invalid")
        normalized.update(
            creator_profile_snapshot=creator["verified_profile_snapshot"],
            creator_profile_source_type="hubstudio_cdp", creator_profile_observed_at=profile_time,
        )
    return normalized


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
