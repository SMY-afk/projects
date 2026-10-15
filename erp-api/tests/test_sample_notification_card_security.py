import json
from datetime import UTC, datetime
from types import SimpleNamespace

from erp_api.services.sample_notification_card import (
    build_sample_notification_card,
)


def _unsafe_task() -> SimpleNamespace:
    return SimpleNamespace(
        payload={"assigned_bd_name": "<at id=all></at>\n# BD"},
        feishu_record_id="rec-safe",
        platform_status="PENDING",
        creator_name="<at id=all></at> [click](https://evil.test)",
        creator_username=None,
        creator_level="L7`**",
        creator_pps=None,
        creator_rating=None,
        creator_avatar_object_key=None,
        creator_profile_snapshot={
            "schema_version": 2,
            "bio": "A" * 20_000 + "<at id=all></at>",
            "sales": {
                "category_shares": [
                    {
                        "code": str(index),
                        "label": "[category](https://evil.test)" * 30,
                        "share_bps": 1000,
                    }
                    for index in range(100)
                ]
            },
        },
        creator_profile_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        follower_count=None,
        creator_gmv_minor=None,
        creator_gmv_currency="USD",
        creator_units_sold=None,
        creator_ec_video_view=None,
        creator_content_count=None,
        creator_fulfillment_percentage=None,
        shop_name="<at id=all></at>",
        product_name="[product](https://evil.test)\n# title",
        approve_expiration_at=None,
        source_observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )


def test_card_neutralizes_mentions_and_compacts_oversized_profile() -> None:
    card = build_sample_notification_card(
        _unsafe_task(),
        "https://example.invalid/configure-resource",
        is_test=True,
    )

    encoded = json.dumps(card, ensure_ascii=False).encode("utf-8")
    assert len(encoded) < 28_000
    assert b"<at" not in encoded
    assert "＜at id=all＞＜/at＞" in encoded.decode("utf-8")
    assert encoded.count(b'"type": "open_url"') == 1
    assert "打开飞书处理" in encoded.decode("utf-8")
