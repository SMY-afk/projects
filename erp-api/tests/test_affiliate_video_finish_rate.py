from datetime import date
from uuid import UUID

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_video_metric_parser import (
    parse_video_export_rows,
    parse_video_page_payload,
)


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=UUID("e4408786-af60-545e-8f8c-5ef22a71e675"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 1),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_video_finish_rate_accepts_multiple_completions_per_view() -> None:
    payload = {
        "code": 0,
        "message": "ok",
        "data": {
            "video_list_segments_v2": [
                {
                    "time_descriptor": {
                        "start_time": 1,
                        "end_time": 2,
                        "timezone_offset": -7,
                    },
                    "total": 1,
                    "video_performances": [
                        {
                            "creator_base": {
                                "oec_id": "creator-1",
                                "handle_name": "creator",
                            },
                            "product_base_list": [],
                            "product_ids": [],
                            "video_info": {
                                "item_id": "video-1",
                                "create_time": None,
                            },
                            "video_metrics": {
                                "video_gmv": None,
                                "video_orders_cnt": None,
                                "video_product_impressions_cnt": None,
                                "video_views_cnt": None,
                                "video_finish_rate": {"value": "1.2"},
                            },
                        }
                    ],
                }
            ]
        },
    }

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].finish_rate == "1.2"


def test_video_export_finish_rate_accepts_multiple_completions_per_view() -> None:
    result = parse_video_export_rows(
        [{"videoId": "video-1", "currency": "USD", "finishRate": "1.2"}],
        query=_query(),
    )

    assert result[0].finish_rate == "1.2"
