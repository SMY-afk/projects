from app.parsers.seller_video_parser import (
    parse_video_completion_response,
    seller_video_ids,
)


def _point(second: int, value: str, formatted: str) -> dict[str, object]:
    return {
        "base_time": second,
        "value": {
            "base_indicator_value": {
                "decimal_value": value,
                "formatted_value": formatted,
            }
        },
    }


def test_video_ids_are_extracted_and_deduplicated_from_list_response() -> None:
    payload = {
        "data": {
            "segments": [
                {
                    "timed_lists": [
                        {
                            "stats": [
                                {"video_meta": {"id": "video-1"}},
                                {"video_meta": {"id": "video-1"}},
                                {"video_meta": {"id": "video-2"}},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    assert seller_video_ids(payload) == ["video-1", "video-2"]


def test_completion_uses_last_full_second_not_end_boundary() -> None:
    payload = {
        "code": 0,
        "data": {
            "segments": [
                {
                    "item_id": "9079740261053642911",
                    "data_list": [
                        {
                            "indicator_type": 1,
                            "indicator_name": "Retention",
                            "trend_data": [
                                _point(-1, "1", "100.00%"),
                                _point(2, "0.077947", "7.79%"),
                                _point(6, "0.032319", "3.23%"),
                                _point(8, "0.025", "2.50%"),
                                _point(15, "0.015", "1.50%"),
                                _point(22, "0.008", "0.80%"),
                                _point(27, "0.004025", "0.40%"),
                                _point(28, "0.001761", "0.18%"),
                                _point(29, "0", "0.00%"),
                            ],
                        },
                        {
                            "indicator_type": 2,
                            "trend_data": [_point(28, "0.2", "20.00%")],
                        },
                    ],
                }
            ]
        },
    }

    record = parse_video_completion_response(payload)[0]

    assert record["platform_id"] == ("seller_video_completion:9079740261053642911")
    assert record["data_type"] == "seller_video_completion"
    assert record["raw_data"]["completion_second"] == 28
    assert record["raw_data"]["completion_rate"] == "0.001761"
    assert record["raw_data"]["completion_rate_formatted"] == "0.18%"
    assert record["raw_data"]["calculation"] == "last_full_second_retention"
    assert record["raw_data"]["retention_stages"] == {
        "2s": {"second": 2, "rate": "0.077947", "formatted": "7.79%"},
        "6s": {"second": 6, "rate": "0.032319", "formatted": "3.23%"},
        "25%": {"second": 8, "rate": "0.025", "formatted": "2.50%"},
        "50%": {"second": 15, "rate": "0.015", "formatted": "1.50%"},
        "75%": {"second": 22, "rate": "0.008", "formatted": "0.80%"},
        "100%": {"second": 28, "rate": "0.001761", "formatted": "0.18%"},
    }


def test_completion_parser_rejects_missing_retention_series() -> None:
    payload = {
        "code": 0,
        "data": {"segments": [{"item_id": "video-1", "data_list": []}]},
    }

    assert parse_video_completion_response(payload) == []
