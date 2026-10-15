from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.tiktok_transport import TikTokApiError

GROUP_OBSERVED_AT = datetime(2026, 10, 8, 8, 48, 53, tzinfo=UTC)


def _payload() -> dict[str, object]:
    return {
        "code": 0,
        "request_id": "body-request-id",
        "data": {
            "sample_applications": [
                {
                    "id": "sample-1",
                    "status": "PENDING",
                    "creator": {"id": "creator-1"},
                    "product": {"id": "product-1"},
                }
            ],
            "next_page_token": "next-1",
            "total_count": 7,
        },
    }


def test_parser_reuses_official_page_contract_for_records_and_pagination() -> None:
    page = parse_hubstudio_sample_response(
        _payload(), platform_request_id="header-request-id"
    )

    assert page.applications[0]["id"] == "sample-1"
    assert page.next_page_token == "next-1"
    assert page.total_count == 7
    assert page.platform_request_id == "header-request-id"


def test_parser_keeps_current_creator_group_as_one_multi_product_application() -> None:
    payload = {
        "code": 0,
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {
                        "creator_id": "creator-1",
                        "name": "creator_name",
                        "nick_name": "Creator",
                        "follower_num": "25672",
                        "gmv": "$16,631.41",
                        "fulfillment_rate": "71.04%",
                        "content_video_views": "487",
                        "pps_score": "4.3",
                        "item_sold": "778",
                    },
                    "apply_infos": [
                        {
                            "apply_id": "sample-1",
                            "product_id": "product-1",
                            "product_title": "Product",
                            "sku_id": "sku-1",
                            "sku_desc": "White",
                            "sku_image": "https://example.com/image.jpg",
                            "commission_rate": "1200",
                            "sku_stock": 20,
                            "curr_status": 10,
                            "can_be_approved": True,
                            "source_type": 1,
                            "create_time": "1789088309846",
                            "expired_in": 575017474,
                            "main_order_id": "order-1",
                        },
                        {
                            "apply_id": "sample-2",
                            "product_id": "product-2",
                            "product_title": "Product 2",
                            "curr_status": 12,
                        },
                    ],
                }
            }
        ],
        "has_more": True,
        "total_count": 1,
    }

    page = parse_hubstudio_sample_response(
        payload,
        platform_request_id="group-request-id",
        observed_at=GROUP_OBSERVED_AT,
    )

    assert len(page.applications) == 1
    first = page.applications[0]
    assert first["status"] == "PENDING"
    assert first["id"] == "sample-1"
    assert first["creator"]["username"] == "creator_name"
    assert first["creator"]["follower_count"] == 25672
    assert first["creator"]["gmv"] == {
        "amount": "16631.41",
        "currency": "USD",
    }
    assert first["creator"]["fulfillment_percentage"] == "71.04"
    assert first["commission_rate"] == "0.12"
    assert first["available_quantity"] == 20
    assert first["application_time"] == 1789088309
    assert first["is_proactive_invitation"] is True
    assert first["approve_expiration_time"] == int(
        (GROUP_OBSERVED_AT + timedelta(milliseconds=575_017_474)).timestamp()
    )
    assert [item["application_id"] for item in first["products"]] == [
        "sample-1",
        "sample-2",
    ]
    assert [item["application_time"] for item in first["products"]] == [
        1789088309,
        None,
    ]
    assert [item["is_proactive_invitation"] for item in first["products"]] == [
        True,
        None,
    ]
    assert [item["product"]["id"] for item in first["products"]] == [
        "product-1",
        "product-2",
    ]
    assert first["source_item_ids"] == ["sample-1", "sample-2"]
    assert page.next_page_token == "ui_next"
    assert page.total_count is None


def test_group_expiration_is_relative_to_response_observation_time() -> None:
    observed_at = datetime(2026, 10, 8, 8, 48, 53, tzinfo=UTC)
    payload = {
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {"creator_id": "creator-1"},
                    "apply_infos": [
                        {
                            "apply_id": "sample-1",
                            "product_id": "product-1",
                            "sku_id": "sku-1",
                            "curr_status": 10,
                            "can_be_approved": True,
                            "create_time": "1790993705818",
                            "expired_in": 149_099_783,
                        }
                    ],
                }
            }
        ],
        "has_more": False,
        "total_count": 1,
    }

    page = parse_hubstudio_sample_response(
        payload,
        platform_request_id=None,
        observed_at=observed_at,
    )

    assert page.applications[0]["approve_expiration_time"] == int(
        (observed_at + timedelta(milliseconds=149_099_783)).timestamp()
    )


def test_parser_groups_multiple_pending_products_for_one_creator() -> None:
    payload = {
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {"creator_id": "creator-1"},
                    "apply_infos": [
                        {
                            "apply_id": "sample-1",
                            "product_id": "product-1",
                            "sku_id": "sku-1",
                            "sku_image": "https://example.com/one.jpg",
                            "curr_status": 10,
                            "create_time": "1789088309000",
                        },
                        {
                            "apply_id": "sample-2",
                            "product_id": "product-2",
                            "sku_id": "sku-2",
                            "sku_image": "https://example.com/two.jpg",
                            "curr_status": 10,
                            "create_time": "1789091909000",
                        },
                    ],
                }
            }
        ],
        "has_more": False,
    }

    page = parse_hubstudio_sample_response(
        payload, platform_request_id=None, observed_at=GROUP_OBSERVED_AT
    )

    assert len(page.applications) == 1
    application = page.applications[0]
    assert application["status"] == "PENDING"
    assert application["id"] == "sample-1"
    assert application["application_time"] == 1789088309
    assert [item["application_id"] for item in application["products"]] == [
        "sample-1",
        "sample-2",
    ]
    assert [item["product"]["id"] for item in application["products"]] == [
        "product-1",
        "product-2",
    ]


def test_parser_keeps_all_product_ids_when_creator_items_have_mixed_statuses() -> None:
    payload = {
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {"creator_id": "creator-1"},
                    "apply_infos": [
                        {
                            "apply_id": "sample-shipped",
                            "product_id": "product-shipped",
                            "curr_status": 30,
                        },
                        {
                            "apply_id": "sample-pending",
                            "product_id": "product-pending",
                            "curr_status": 10,
                        },
                    ],
                }
            }
        ],
        "has_more": False,
    }

    page = parse_hubstudio_sample_response(
        payload, platform_request_id=None, observed_at=GROUP_OBSERVED_AT
    )

    application = page.applications[0]
    assert application["status"] == "PENDING"
    assert [item["product"]["id"] for item in application["products"]] == [
        "product-shipped",
        "product-pending",
    ]


def test_parser_keeps_real_tiktok_id_for_single_creator_application() -> None:
    payload = {
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {"creator_id": "creator-1"},
                    "apply_infos": [
                        {
                            "apply_id": "9415449469306011580",
                            "product_id": "product-1",
                            "curr_status": 10,
                        }
                    ],
                }
            }
        ],
        "has_more": False,
    }

    page = parse_hubstudio_sample_response(
        payload, platform_request_id=None, observed_at=GROUP_OBSERVED_AT
    )

    assert page.applications[0]["id"] == "9415449469306011580"


def test_parser_rejects_non_mapping_and_changed_payload_shape() -> None:
    with pytest.raises(TikTokApiError, match="invalid"):
        parse_hubstudio_sample_response([], platform_request_id=None)

    with pytest.raises(TikTokApiError, match="invalid"):
        parse_hubstudio_sample_response(
            {"data": {"sample_applications": {}}},
            platform_request_id=None,
        )


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (11, "UNKNOWN_11"),
        (20, "AWAITING_SHIPMENT"),
        (30, "SHIPPED"),
        (40, "CONTENT_PENDING"),
        (51, "CANCELLED"),
        (56, "CANCELLED"),
        (61, "UNKNOWN_61"),
        (100, "COMPLETED"),
    ],
)
def test_parser_maps_all_page_statuses(code: int, status: str) -> None:
    payload = {
        "agg_info": [
            {
                "apply_deatil": {
                    "creator_info": {"creator_id": "creator-1"},
                    "apply_infos": [
                        {
                            "apply_id": "sample-1",
                            "product_id": "product-1",
                            "curr_status": code,
                        }
                    ],
                }
            }
        ],
        "has_more": False,
    }

    page = parse_hubstudio_sample_response(
        payload, platform_request_id=None, observed_at=GROUP_OBSERVED_AT
    )

    assert page.applications[0]["status"] == status
