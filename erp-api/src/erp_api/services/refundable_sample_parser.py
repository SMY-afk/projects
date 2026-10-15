"""Verified TikTok refundable apply/list protocol, not free review tab=10."""

from collections.abc import Mapping
from datetime import datetime

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.refundable_identity_guard import QUARANTINE_KEY, QUARANTINE_REASON
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)

REFUNDABLE_PATH = "/api/v1/affiliate/sample/refundable/apply/list"
REFUNDABLE_TAB_STATUSES = {
    1: {20: "REFUNDABLE_AWAITING_SHIPMENT"},
    2: {30: "REFUNDABLE_SHIPPED"},
    3: {40: "REFUNDABLE_CONTENT_PENDING"},
    4: {100: "REFUNDABLE_REFUNDED"},
    5: {53: "REFUNDABLE_NOT_REFUNDED"},
    6: {58: "REFUNDABLE_CANCELLED"},
}


def validate_refundable_request(request: object) -> dict:
    if not isinstance(request, dict):
        raise TypeError("Refundable request is missing")
    for key in ("tab_type", "cur_page", "page_size"):
        if type(request.get(key)) is not int:
            raise ValueError("Refundable pagination scope is invalid")
    if (request["tab_type"] not in REFUNDABLE_TAB_STATUSES
            or request["cur_page"] < 1 or not 1 <= request["page_size"] <= 100):
        raise ValueError("Refundable pagination scope is invalid")
    search = request.get("search_param")
    if not isinstance(search, dict) or any(value not in (None, "") for value in search.values()):
        raise ValueError("Refundable filtered response cannot certify a batch")
    return request


def parse_refundable_sample_page(
    payload: object, *, request: object, request_id: str | None, observed_at: datetime,
) -> TikTokSampleApplicationPage:
    request = validate_refundable_request(request)
    if observed_at.tzinfo is None or not isinstance(payload, Mapping) or payload.get("code") != 0:
        raise ValueError("Refundable response is unavailable")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise TypeError("Refundable response data is invalid")
    records, total = data.get("apply_records", []), data.get("total_count")
    if not isinstance(records, list) or type(total) is not int or total < 0:
        raise ValueError("Refundable response pagination is invalid")
    if len(records) > request["page_size"]:
        raise ValueError("Refundable page exceeds request size")
    has_more = request["cur_page"] * request["page_size"] < total
    if has_more and len(records) != request["page_size"]:
        raise ValueError("Refundable intermediate page is incomplete")
    return TikTokSampleApplicationPage(
        applications=tuple(_normalize(item, request["tab_type"]) for item in records),
        next_page_token=str(request["cur_page"] + 1) if has_more else None,
        total_count=total, platform_request_id=request_id,
    )


def _identity(value, *, account=False):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Refundable stable identity is missing")
    value = value.strip().lstrip("@") if account else value.strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError("Refundable stable identity contains whitespace")
    return value


def _normalize(item, tab):
    if not isinstance(item, Mapping):
        raise TypeError("Refundable application is invalid")
    application_id = _identity(item.get("apply_id"))
    creator_id = _identity(item.get("creator_id"))
    try:
        username = _identity(item.get("creator_name"), account=True)
    except ValueError:
        username = None
    status_code = item.get("status")
    if type(status_code) is not int:
        raise ValueError("Refundable source status is invalid")
    # Unknown codes are retained for audit, never promoted to assignable states.
    status = REFUNDABLE_TAB_STATUSES[tab].get(status_code, f"REFUNDABLE_UNKNOWN_{status_code}")
    safe = sanitize_capture_payload(dict(item))
    return {
        "id": application_id, "sample_type": "refundable", "status": status,
        "creator": {"creator_open_id": creator_id, "username": username,
                    "nickname": item.get("creator_nick_name")},
        "product": {"id": _identity(item.get("product_id")),
                    "title": item.get("product_name"), "sku_id": item.get("sku_id"),
                    "sku_name": item.get("sku_desc"), "sku_image_url": item.get("sku_image")},
        "order_id": _identity(item.get("main_order_id")),
        "is_approvable": None, "application_time": None, "approve_expiration_time": None,
        "refundable_contract_verified": True, "refundable_raw": safe,
        "refundable_source_tab": tab,
        **({QUARANTINE_KEY: QUARANTINE_REASON} if username is None else {}),
    }
