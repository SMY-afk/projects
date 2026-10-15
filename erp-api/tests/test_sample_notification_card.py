import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from erp_api.services.sample_notification_card import (
    build_sample_notification_card,
)


def _task(**overrides):
    values = {
        "payload": {"assigned_bd_name": "刘诚"},
        "feishu_record_id": "rec/1",
        "platform_status": "PENDING",
        "creator_name": "Kierra 🎀⚡",
        "creator_username": "kierra_b_lifestyle",
        "creator_level": "L4",
        "creator_pps": Decimal("4.0"),
        "creator_rating": Decimal("5.0"),
        "creator_avatar_object_key": "sample/creator-avatars/t/s/c/hash.jpg",
        "creator_profile_snapshot": {
            "schema_version": 2,
            "bio": "Lifestyle creator in Virginia",
            "location": "Virginia",
            "rating_count": 4,
            "pps": {
                "band_code": "MEDIUM",
                "band_label": "中等",
                "description": "近 30 天带货内容和选品表现良好。",
            },
            "sample_score": {
                "overall": "86",
                "grade_code": "EXCELLENT",
                "grade_label": "优秀",
                "content_effect": "90",
                "content_effect_percentile_bps": 8900,
                "posting_freshness": "85",
                "posting_freshness_percentile_bps": 8100,
                "selling_power": "80",
                "selling_power_percentile_bps": 8000,
                "posting_effect": "94",
                "posting_effect_percentile_bps": 9200,
            },
            "sales": {
                "gmv_minor": 850000,
                "units_sold": 167,
                "order_count": 167,
                "gmv_per_mille_minor": 640,
                "average_order_value_minor": 5420,
                "channel_shares": [
                    {"code": "video", "label": "视频", "share_bps": 10000}
                ],
                "category_shares": [
                    {"code": "textile", "label": "纺织品", "share_bps": 9037}
                ],
                "window": {
                    "start_at": "2026-08-08T00:00:00-07:00",
                    "end_at": "2026-09-07T23:59:59-07:00",
                    "timezone": "GMT-7",
                },
            },
            "cooperation": {
                "average_commission_rate_bps": 1000,
                "product_count": 16,
                "brand_collaboration_count": 52,
            },
            "video": {
                "gmv_minor": 830000,
                "gmv_per_mille_minor": 520,
                "count": 28,
                "average_view_count": 12500,
                "average_engagement_rate_bps": 735,
            },
            "live": {
                "gmv_minor": 20000,
                "gmv_per_mille_minor": 110,
                "count": 3,
                "average_engagement_rate_bps": 280,
            },
            "trends": {
                "gmv_minor": 850000,
                "units_sold": 167,
                "followers": 741000,
                "video_views": 350000,
                "engagement_rate_bps": 735,
            },
            "creator_categories": [
                {"id": "textile", "label": "Textiles & Soft Furnishings"}
            ],
            "audience": {
                "gender": [
                    {"code": "female", "label": "女性", "share_bps": 7361},
                    {"code": "male", "label": "男性", "share_bps": 2639},
                ],
                "age": [
                    {"code": "35-44", "label": "35-44", "share_bps": 2850},
                    {"code": "45-54", "label": "45-54", "share_bps": 3820},
                ],
                "top_regions": [
                    {"code": "texas", "label": "Texas", "share_bps": 830},
                    {"code": "georgia", "label": "Georgia", "share_bps": 610},
                ],
            },
        },
        "creator_profile_observed_at": datetime(2026, 9, 10, tzinfo=UTC),
        "follower_count": 741_000,
        "creator_gmv_minor": 850_000,
        "creator_gmv_currency": "USD",
        "creator_units_sold": 167,
        "creator_ec_video_view": 12_500,
        "creator_content_count": 28,
        "creator_fulfillment_percentage": Decimal("97.35"),
        "shop_name": "Akeleo Toys",
        "product_name": "RC Car Sample",
        "approve_expiration_at": datetime(2026, 9, 10, 4, tzinfo=UTC),
        "source_observed_at": datetime(2026, 9, 10, 0, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_card_has_compact_metrics_and_two_safe_links() -> None:
    card = build_sample_notification_card(
        _task(),
        "https://example.invalid/configure-resource",
        is_test=True,
        avatar_img_key="img_v2_safe",
        product_img_keys=("img_v2_product_1", "img_v2_product_2"),
    )

    assert card["schema"] == "2.0"
    assert card["config"]["width_mode"] == "compact"
    assert card["header"]["template"] == "orange"
    elements = card["body"]["elements"]
    panels = [item for item in elements if item.get("tag") == "collapsible_panel"]
    assert [item["header"]["title"]["content"] for item in panels] == [
        "达人资料与样品表现",
        "销量与合作",
        "视频、直播与趋势",
        "粉丝画像",
    ]
    assert all(item["expanded"] is False for item in panels)
    nested_images = [
        child
        for element in elements
        for column in element.get("columns", [])
        for child in column.get("elements", [])
        if child.get("tag") == "img"
    ]
    assert {item["img_key"] for item in nested_images} == {
        "img_v2_safe",
        "img_v2_product_1",
        "img_v2_product_2",
    }
    avatar_images = [item for item in nested_images if item.get("preview") is False]
    assert len(avatar_images) == 1
    assert "size" not in avatar_images[0]
    assert "corner_radius" not in avatar_images[0]
    product_images = [item for item in nested_images if item.get("preview") is True]
    assert [item["img_key"] for item in product_images] == [
        "img_v2_product_1",
        "img_v2_product_2",
    ]
    assert [item["alt"]["content"] for item in product_images] == [
        "Product image 1",
        "Product image 2",
    ]
    assert all("size" not in item for item in product_images)
    assert all(item["preview"] is True for item in product_images)
    product_image_set_index = next(
        index
        for index, element in enumerate(elements)
        if any(
            child.get("img_key") == "img_v2_product_1"
            for column in element.get("columns", [])
            for child in column.get("elements", [])
        )
    )
    product_image_set = elements[product_image_set_index]
    assert all(
        child.get("tag") == "img"
        for column in product_image_set["columns"]
        for child in column["elements"]
    )
    assignment_content = elements[product_image_set_index + 1]["text"]["content"]
    assert "审核截止" in assignment_content
    assert "分配 BD" in assignment_content
    buttons = [
        child
        for element in elements
        for column in element.get("columns", [])
        for child in column.get("elements", [])
        if child.get("tag") == "button"
    ]
    assert buttons[0]["behaviors"][0]["default_url"].endswith("record=rec%2F1")
    assert buttons[1]["behaviors"][0]["default_url"] == (
        "https://www.tiktok.com/@kierra_b_lifestyle"
    )
    content = json.dumps(card, ensure_ascii=False)
    assert "商品图片" not in content
    assert len(content.encode("utf-8")) < 30_000
    assert "Akeleo Toys（本土店）" in content
    for expected in (
        "样品分",
        "86/100",
        "销量与合作",
        "粉丝画像",
        "成交渠道",
        "类目收入",
        "视频数据",
        "Video GPM",
        "直播数据",
        "LIVE GPM",
        "趋势摘要",
        "女性 73.61%",
        "35-44 28.50%",
        "Texas 8.30%",
        "2026-08-08",
        "2026-09-07",
    ):
        assert expected in content


def test_card_handles_missing_optional_metrics() -> None:
    task = _task(
        creator_username=None,
        creator_level=None,
        creator_pps=None,
        creator_rating=None,
        follower_count=None,
        creator_gmv_minor=None,
        creator_gmv_currency=None,
        creator_units_sold=None,
        creator_ec_video_view=None,
        creator_content_count=None,
        creator_fulfillment_percentage=None,
        creator_avatar_object_key=None,
        creator_profile_snapshot=None,
        creator_profile_observed_at=None,
        source_observed_at=None,
    )

    card = build_sample_notification_card(
        task,
        "https://example.invalid/configure-resource",
        is_test=False,
    )

    assert card["schema"] == "2.0"
    elements = card["body"]["elements"]
    panels = [item for item in elements if item.get("tag") == "collapsible_panel"]
    assert len(panels) == 4
    assert all(item["expanded"] is False for item in panels)
    assert all("暂无数据" in json.dumps(item, ensure_ascii=False) for item in panels)
    buttons = [
        child
        for element in elements
        for column in element.get("columns", [])
        for child in column.get("elements", [])
        if child.get("tag") == "button"
    ]
    assert len(buttons) == 1
    assert "暂无附加画像数据" in json.dumps(card, ensure_ascii=False)


def test_card_rejects_missing_bd_or_unsafe_record_url() -> None:
    with pytest.raises(ValueError, match="BD name"):
        build_sample_notification_card(
            _task(payload={}),
            "https://example.invalid/configure-resource",
            is_test=True,
        )
    with pytest.raises(ValueError, match="record URL"):
        build_sample_notification_card(
            _task(),
            "javascript:alert('{record_id}')",
            is_test=True,
        )


def test_card_rejects_invalid_feishu_image_key() -> None:
    with pytest.raises(ValueError, match="image key"):
        build_sample_notification_card(
            _task(),
            "https://example.invalid/configure-resource",
            is_test=True,
            avatar_img_key="invalid image key",
        )
    with pytest.raises(ValueError, match="image key"):
        build_sample_notification_card(
            _task(),
            "https://example.invalid/configure-resource",
            is_test=True,
            product_img_keys=("invalid image key",),
        )
