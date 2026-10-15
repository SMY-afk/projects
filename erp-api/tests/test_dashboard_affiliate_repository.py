from datetime import date
from uuid import UUID

from erp_api.services.dashboard_affiliate_metrics import (
    efficiency_payload,
    level_items,
)


def test_level_items_returns_every_level_and_uses_known_total() -> None:
    items = level_items({"L0": 3, "L2": 1})

    assert [item["level"] for item in items] == [
        "L7",
        "L6",
        "L5",
        "L4",
        "L3",
        "L2",
        "L1",
        "L0",
    ]
    assert next(item for item in items if item["level"] == "L0")["share"] == 75.0


def test_efficiency_payload_ranks_creators_and_joins_sample_status() -> None:
    shop_id = UUID("b252abf4-86c8-539b-956f-1fd1b0892dfe")
    pages = [
        (
            {"id": shop_id, "name": "Demo Shop"},
            {
                "items": [
                    {
                        "id": "creator-low",
                        "username": "low",
                        "creatorOpenId": "open-low",
                        "affiliateGmvMinor": 100,
                        "affiliateVideoCount": 2,
                    },
                    {
                        "id": "creator-high",
                        "username": "high",
                        "creatorOpenId": "open-high",
                        "affiliateGmvMinor": 300,
                        "affiliateVideoCount": 3,
                    },
                ]
            },
        )
    ]
    statuses = {(shop_id, "id:open-high"): "SHIPPED"}

    result = efficiency_payload(
        pages,
        statuses,
        (date(2026, 8, 21), date(2026, 9, 19)),
        expected_shop_count=1,
    )

    assert result["complete"] is True
    assert result["totalGmvMinor"] == 400
    assert result["rows"][0]["username"] == "high"
    assert result["rows"][0]["rank"] == 1
    assert result["rows"][0]["sampleStatus"] == "SHIPPED"
    assert result["rows"][0]["gmvPerVideoMinor"] == 100
    assert result["rows"][0]["cumulativeGmvShare"] == 75.0
