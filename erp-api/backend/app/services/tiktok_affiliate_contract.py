from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

TARGET_METHOD = "POST"
TARGET_PATH = "/api/oec/pay/statement/order/seller/orders/list"


def platform_shop_id(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get("oec_seller_id")
    if not values:
        return None
    value = values[0].strip()
    return value or None


def affiliate_pagination(
    payload: Mapping[str, object],
) -> tuple[str | None, bool]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None, False
    raw_cursor = data.get("next_cursor")
    next_cursor = str(raw_cursor).strip() if raw_cursor is not None else None
    return next_cursor or None, data.get("has_more") is True


def is_affiliate_order_payload(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    data = payload.get("data")
    return isinstance(data, Mapping) and isinstance(
        data.get("sku_order_list"),
        list,
    )
