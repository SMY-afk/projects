from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from erp_api.services.affiliate_center_capture_policy import (
    sanitize_capture_payload,
)
from erp_api.services.hubstudio_sample_fields import (
    application_time as _application_time,
)
from erp_api.services.hubstudio_sample_fields import (
    commission_rate as _commission_rate,
)
from erp_api.services.hubstudio_sample_fields import (
    expiration_time as _expiration_time,
)
from erp_api.services.hubstudio_sample_fields import (
    integer_text as _integer_text,
)
from erp_api.services.hubstudio_sample_fields import (
    money as _money,
)
from erp_api.services.hubstudio_sample_fields import (
    percentage as _percentage,
)
from erp_api.services.hubstudio_sample_fields import (
    text as _text,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
    parse_sample_application_page,
)
from erp_api.services.tiktok_transport import TikTokApiError, TikTokResponse


def parse_hubstudio_sample_response(
    payload: object,
    *,
    platform_request_id: str | None,
    observed_at: datetime | None = None,
) -> TikTokSampleApplicationPage:
    """Parse a CDP response through the official sample-page contract."""
    if not isinstance(payload, Mapping):
        raise TikTokApiError(
            "TikTok sample application response is invalid.",
            code="invalid_response",
            status_code=502,
            request_id=platform_request_id,
        )
    if "refundable_response" in payload:
        from erp_api.services.refundable_sample_parser import parse_refundable_sample_page

        if observed_at is None:
            raise ValueError("Refundable RAW observation is missing")
        page = parse_refundable_sample_page(
            payload["refundable_response"], request=payload.get("refundable_request"),
            request_id=platform_request_id, observed_at=observed_at,
        )
        profiles = payload.get("refundable_profiles", {})
        if not isinstance(profiles, Mapping):
            raise ValueError("Refundable profiles are invalid")
        from erp_api.services.refundable_creator_profile import apply_refundable_profile
        for application in page.applications:
            apply_refundable_profile(application, profiles.get(application["creator"]["username"]))
        return page
    normalized_payload: dict[str, Any] = dict(payload)
    if isinstance(normalized_payload.get("agg_info"), list):
        if observed_at is None or observed_at.tzinfo is None:
            raise _invalid_group_list()
        normalized_payload = _normalize_group_list(
            normalized_payload, observed_at.astimezone(UTC)
        )
    page = parse_sample_application_page(
        TikTokResponse(
            payload=normalized_payload,
            platform_request_id=platform_request_id,
            status_code=200,
        )
    )
    sanitized_applications = tuple(
        _sanitize_application(application) for application in page.applications
    )
    return TikTokSampleApplicationPage(
        applications=sanitized_applications,
        next_page_token=page.next_page_token,
        total_count=page.total_count,
        platform_request_id=page.platform_request_id,
    )


def _normalize_group_list(
    payload: dict[str, Any], observed_at: datetime
) -> dict[str, Any]:
    raw_groups = payload.get("agg_info")
    if not isinstance(raw_groups, list) or not isinstance(
        payload.get("has_more"), bool
    ):
        raise _invalid_group_list()
    total_count = payload.get("total_count")
    if total_count is not None and (
        not isinstance(total_count, int)
        or isinstance(total_count, bool)
        or total_count < 0
    ):
        raise _invalid_group_list()
    applications: list[dict[str, Any]] = []
    for group in raw_groups:
        if not isinstance(group, Mapping):
            raise _invalid_group_list()
        detail = group.get("apply_deatil")
        if not isinstance(detail, Mapping):
            raise _invalid_group_list()
        creator = detail.get("creator_info")
        raw_applications = detail.get("apply_infos")
        if not isinstance(creator, Mapping) or not isinstance(raw_applications, list):
            raise _invalid_group_list()
        applications.append(
            _normalize_creator_group(raw_applications, creator, observed_at)
        )
    return {
        "data": {
            "sample_applications": applications,
            "next_page_token": "ui_next" if payload["has_more"] else None,
            # The group endpoint's total_count is not the cardinality of
            # agg_info and must remain RAW audit evidence only.
            "total_count": None,
        }
    }


_CURRENT_STATUS_PRIORITY = (
    "PENDING",
    "AWAITING_SHIPMENT",
    "SHIPPED",
    "CONTENT_PENDING",
    "COMPLETED",
    "OPS_FAILED",
    "CANCELLED",
)
_TARGET_COLLABORATION_SOURCE_TYPE = 1


def _normalize_creator_group(
    raw_applications: list[object],
    creator: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    creator_id = _text(creator.get("creator_id"))
    if creator_id is None or not raw_applications:
        raise _invalid_group_list()
    items = []
    for raw in raw_applications:
        if not isinstance(raw, Mapping):
            raise _invalid_group_list()
        items.append(_normalize_group_application(raw, creator, observed_at))
    statuses = {item["status"] for item in items}
    current_status = next(
        (status for status in _CURRENT_STATUS_PRIORITY if status in statuses), None
    )
    if current_status is None:
        current_status = str(items[0]["status"])
    current_items = [item for item in items if item["status"] == current_status]
    first = current_items[0]
    parent_id = min((item["id"] for item in items), key=_application_id_sort_key)
    parent = next(item for item in items if item["id"] == parent_id)
    return {
        **first,
        "id": parent_id,
        "status": current_status,
        "product": _aggregate_products(items),
        "products": [_product_item(item) for item in items],
        "is_proactive_invitation": _proactive_invitation(current_items),
        "source_item_ids": [str(item["id"]) for item in items],
        "application_time": parent["application_time"],
        "approve_expiration_time": _earliest_positive(
            current_items, "approve_expiration_time"
        ),
        "is_approvable": any(
            item.get("is_approvable") is True for item in current_items
        ),
    }


def _application_id_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdecimal() else (1, value)


def _product_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "application_id": item["id"],
        "application_time": item.get("application_time"),
        "application_source_type": item.get("application_source_type"),
        "is_proactive_invitation": item.get("is_proactive_invitation"),
        "status": item["status"],
        "product": dict(item["product"]),
    }


def _proactive_invitation(items: list[dict[str, Any]]) -> bool | None:
    values = [item.get("is_proactive_invitation") for item in items]
    if any(value is True for value in values):
        return True
    if values and all(value is False for value in values):
        return False
    return None


def _aggregate_products(items: list[dict[str, Any]]) -> dict[str, Any]:
    products = [item["product"] for item in items]
    return {
        "id": _joined(products, "id"),
        "title": _joined(products, "title"),
        "sku_id": _joined(products, "sku_id"),
        "sku_name": _joined(products, "sku_name"),
        "sku_image_url": next(
            (
                value
                for product in products
                if (value := _text(product.get("sku_image_url"))) is not None
            ),
            None,
        ),
    }


def _joined(products: list[dict[str, Any]], key: str) -> str | None:
    values = []
    for product in products:
        value = _text(product.get(key))
        if value is not None and value not in values:
            values.append(value)
    return "、".join(values) or None


def _earliest_positive(items: list[dict[str, Any]], key: str) -> int | None:
    values = [item.get(key) for item in items]
    valid = [value for value in values if isinstance(value, int) and value > 0]
    return min(valid, default=None)


def _normalize_group_application(
    application: Mapping[str, Any],
    creator: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    application_id = _text(application.get("apply_id"))
    status = _group_status(application.get("curr_status"))
    if application_id is None or status is None:
        raise _invalid_group_list()
    source_type = _integer_text(application.get("source_type"))
    return {
        "id": application_id,
        "status": status,
        "creator": {
            "creator_open_id": _text(creator.get("creator_id")),
            "username": _text(creator.get("name")),
            "nickname": _text(creator.get("nick_name")),
            "follower_count": _integer_text(creator.get("follower_num")),
            "gmv": _money(creator.get("gmv")),
            "fulfillment_percentage": _percentage(creator.get("fulfillment_rate")),
            "performance": {
                "avg_ec_video_play_count": _integer_text(
                    creator.get("content_video_views")
                ),
                "units_sold": _integer_text(creator.get("item_sold")),
                "pps": _text(creator.get("pps_score")),
            },
        },
        "product": {
            "id": _text(application.get("product_id")),
            "title": _text(application.get("product_title")),
            "sku_id": _text(application.get("sku_id")),
            "sku_name": _text(application.get("sku_desc")),
            "sku_image_url": _text(application.get("sku_image")),
        },
        "order_id": _text(application.get("main_order_id")),
        "commission_rate": _commission_rate(application.get("commission_rate")),
        "available_quantity": application.get("sku_stock"),
        "is_approvable": application.get("can_be_approved"),
        "application_source_type": source_type,
        "is_proactive_invitation": source_type == _TARGET_COLLABORATION_SOURCE_TYPE
        if source_type is not None
        else None,
        "application_time": _application_time(application),
        "approve_expiration_time": _expiration_time(application, observed_at),
    }


def _group_status(value: object) -> str | None:
    if value in {11, 61}:
        return f"UNKNOWN_{value}"
    if isinstance(value, int) and 50 <= value < 60:
        return "CANCELLED"
    statuses = {10: "PENDING", 12: "OPS_FAILED", 20: "AWAITING_SHIPMENT"}
    statuses.update({30: "SHIPPED", 40: "CONTENT_PENDING", 100: "COMPLETED"})
    return statuses.get(value)


def _invalid_group_list() -> TikTokApiError:
    return TikTokApiError("TikTok sample group response is invalid.", code="invalid_response", status_code=502)


def _sanitize_application(application: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_capture_payload(application)
    if not isinstance(sanitized, dict):
        raise TikTokApiError(
            "TikTok sample application response is invalid.",
            code="invalid_response",
            status_code=502,
        )
    return sanitized
