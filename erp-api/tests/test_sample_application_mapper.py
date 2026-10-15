from datetime import UTC, datetime
from decimal import Decimal

import pytest

from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    STATUS_LABELS,
    TERMINAL_SAMPLE_STATUSES,
    normalize_sample_application,
    status_label,
)


def test_normalize_sample_application_maps_official_payload() -> None:
    observed_at = datetime(2026, 9, 9, tzinfo=UTC)
    payload = {
        "id": "application-1",
        "status": "PENDING",
        "commission_rate": "0.125",
        "available_quantity": 4,
        "is_approvable": True,
        "application_time": 1789088309,
        "approve_expiration_time": 1789000000,
        "creator": {
            "creator_open_id": "creator-1",
            "username": "creator_name",
            "nickname": "Creator",
            "follower_count": 1234,
            "content_count": 18,
            "ec_video_view": 2400,
            "fulfillment_percentage": "62.50",
            "gmv": {"amount": "56,100.97", "currency": "usd"},
            "performance": {
                "avg_ec_video_play_count": 2600,
                "ec_video_count": 480,
                "post_rate": "7350",
                "units_sold": 811,
                "pps": "4.2",
                "rating": "4.8",
            },
        },
        "product": {
            "id": "product-1",
            "title": "Product",
            "sku_id": "sku-1",
            "sku_name": "Blue",
        },
    }

    result = normalize_sample_application(payload, observed_at=observed_at)

    assert result["platform_application_id"] == "application-1"
    assert result["creator_username"] == "creator_name"
    assert result["commission_rate"] == Decimal("0.125")
    assert result["creator_gmv_minor"] == 5_610_097
    assert result["creator_gmv_currency"] == "USD"
    assert result["creator_level"] == "L3"
    assert result["creator_content_count"] == 480
    assert result["creator_ec_video_view"] == 2600
    assert result["creator_fulfillment_percentage"] == Decimal("62.50")
    assert result["creator_units_sold"] == 811
    assert result["creator_pps"] == Decimal("4.2")
    assert result["creator_rating"] == Decimal("4.8")
    assert result["tiktok_applied_at"] is None
    assert result["source_observed_at"] == observed_at


def test_normalize_sample_application_falls_back_to_performance_post_rate() -> None:
    result = normalize_sample_application(
        {
            "id": "application-performance-post-rate",
            "status": "PENDING",
            "creator": {
                "performance": {"post_rate": "9772"},
            },
            "product": {},
        },
        observed_at=datetime.now(UTC),
    )

    assert result["creator_fulfillment_percentage"] == Decimal("97.72")


def test_normalize_sample_application_does_not_classify_non_usd_gmv() -> None:
    result = normalize_sample_application(
        {
            "id": "application-2",
            "status": "PENDING",
            "creator": {"gmv": {"amount": "100000", "currency": "EUR"}},
            "product": {},
        },
        observed_at=datetime.now(UTC),
    )

    assert result["creator_gmv_minor"] == 10_000_000
    assert result["creator_gmv_currency"] == "EUR"
    assert result["creator_level"] is None


def test_normalize_sample_application_preserves_hubstudio_source() -> None:
    result = normalize_sample_application(
        {
            "id": "sample-cdp-1",
            "status": "PENDING",
            "application_time": 1789088309,
            "creator": {},
            "product": {},
        },
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        source_type="hubstudio_cdp",
    )

    assert result["source_type"] == "hubstudio_cdp"
    assert result["tiktok_applied_at"] == datetime.fromtimestamp(1789088309, tz=UTC)


def test_normalize_grouped_application_keeps_all_current_product_fields() -> None:
    result = normalize_sample_application(
        {
            "id": "creator-group:abc",
            "status": "PENDING",
            "creator": {"creator_open_id": "creator-1"},
            "product": {},
            "products": [
                {
                    "application_id": "sample-1",
                    "status": "PENDING",
                    "product": {
                        "id": "product-1",
                        "title": "Product One",
                        "sku_id": "sku-1",
                        "sku_name": "Blue",
                        "sku_image_url": "https://example.com/one.jpg",
                    },
                },
                {
                    "application_id": "sample-2",
                    "status": "PENDING",
                    "product": {
                        "id": "product-2",
                        "title": "Product Two",
                        "sku_id": "sku-2",
                        "sku_name": "Red",
                        "sku_image_url": "https://example.com/two.jpg",
                    },
                },
            ],
        },
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
        source_type="hubstudio_cdp",
    )

    assert result["product_id"] == "product-1、product-2"
    assert result["sku_id"] == "sku-1、sku-2"
    assert result["product_title"] == "Product One、Product Two"
    assert result["sku_name"] == "Blue、Red"
    assert result["product_image_urls"] == [
        "https://example.com/one.jpg",
        "https://example.com/two.jpg",
    ]
    assert result["is_current_projection"] is True


def test_official_and_cdp_sources_share_the_same_normalized_business_fields() -> None:
    payload = {
        "id": "sample-shared-1",
        "status": "SHIPPED",
        "creator": {"username": "creator-one", "follower_count": 1200},
        "product": {"id": "product-1", "title": "Product"},
    }
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)

    official = normalize_sample_application(
        payload, observed_at=observed_at, source_type="official_api"
    )
    cdp = normalize_sample_application(
        payload, observed_at=observed_at, source_type="hubstudio_cdp"
    )

    assert official | {"source_type": "hubstudio_cdp"} == cdp


def test_common_normalizer_sanitizes_raw_payload_for_both_sources() -> None:
    payload = {
        "id": "sample-sensitive-1",
        "status": "PENDING",
        "token": "must-not-persist",
        "sign": "must-not-persist",
        "creator": {"username": "creator", "cookie": "must-not-persist"},
        "product": {"id": "product-1", "shop_cipher": "must-not-persist"},
    }

    for source_type in ("official_api", "hubstudio_cdp"):
        normalized = normalize_sample_application(
            payload,
            observed_at=datetime(2026, 9, 10, tzinfo=UTC),
            source_type=source_type,
        )
        raw_payload = normalized["raw_payload"]
        assert "token" not in raw_payload
        assert "sign" not in raw_payload
        assert "cookie" not in raw_payload["creator"]
        assert "shop_cipher" not in raw_payload["product"]


def test_normalize_sample_application_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match="missing id or status"):
        normalize_sample_application(
            {"creator": {}, "product": {}}, observed_at=datetime.now(UTC)
        )


def test_sample_statuses_have_stable_chinese_labels_and_poll_groups() -> None:
    assert status_label("PENDING") == "待审核"
    assert status_label("AWAITING_SHIPMENT") == "待发货"
    assert status_label("SHIPPED") == "已发货"
    assert status_label("CONTENT_PENDING") == "处理中"
    assert status_label("COMPLETED") == "已完成"
    assert status_label("UNKNOWN") == "UNKNOWN"
    assert ACTIVE_SAMPLE_STATUSES.isdisjoint(TERMINAL_SAMPLE_STATUSES)
    assert "CANCELLED" not in TERMINAL_SAMPLE_STATUSES
    assert ACTIVE_SAMPLE_STATUSES | TERMINAL_SAMPLE_STATUSES == (
        frozenset(STATUS_LABELS) - {"CANCELLED"}
    )


@pytest.mark.parametrize(
    ("platform_status", "expected_label"),
    [
        ("PENDING", "待审核"),
        ("AWAITING_SHIPMENT", "待发货"),
        ("SHIPPED", "已发货"),
        ("CONTENT_PENDING", "处理中"),
        ("COMPLETED", "已完成"),
        ("OPS_COMPLETED", "已完成"),
        ("REJECT_CANCELLED", "已取消-审核拒绝"),
        ("OVERDUE_CANCELLED", "已取消-审核超时"),
        ("UNFULFILL_CANCELLED", "已取消-未履约"),
        ("DEL_OPEN_COLLAB", "已取消-合作计划删除"),
        ("SELLER_NOT_SHIP_CANCELLED", "已取消-商家未发货"),
        ("WITHDRAW_CANCELLED", "已取消-达人撤回"),
        ("UNFULFILLABLE_CANCELLED", "已取消-无法履约"),
        ("OPS_CANCELLED", "已取消-运营取消"),
        ("OPS_FAILED", "已取消-运营失败"),
    ],
)
def test_every_known_sample_status_has_an_explicit_chinese_label(
    platform_status: str, expected_label: str
) -> None:
    assert status_label(platform_status) == expected_label
