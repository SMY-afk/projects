import pytest

from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    classify_pagination_mode,
    require_affiliate_payload,
)


def _creator_payload(stats: list[object] | None = None) -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "shop"},
                    "list_control": {
                        "next_pagination": {
                            "has_more": False,
                            "next_page": 2,
                            "total": 1,
                            "total_page": 1,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [] if stats is None else stats,
                        }
                    ],
                }
            ]
        },
    }


def _video_payload(performances: list[object] | None = None) -> dict[str, object]:
    return {
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
                    "video_performances": (
                        [] if performances is None else performances
                    ),
                }
            ]
        },
    }


def test_creator_discriminator_accepts_empty_result_page() -> None:
    assert (
        require_affiliate_payload("creators", _creator_payload())
        == "tiktok_affiliate_creator_filter_list.v1"
    )


def test_video_discriminator_accepts_empty_result_page() -> None:
    assert (
        require_affiliate_payload("videos", _video_payload())
        == "tiktok_affiliate_video_detail_list.v1"
    )


def test_video_discriminator_accepts_zero_total_with_omitted_rows() -> None:
    payload = _video_payload()
    segment = payload["data"]["video_list_segments_v2"][0]
    segment["total"] = 0
    del segment["video_performances"]

    assert (
        require_affiliate_payload("videos", payload)
        == "tiktok_affiliate_video_detail_list.v1"
    )


def test_video_discriminator_rejects_nonzero_total_with_omitted_rows() -> None:
    payload = _video_payload()
    segment = payload["data"]["video_list_segments_v2"][0]
    del segment["video_performances"]

    with pytest.raises(AffiliatePayloadDiscriminatorError):
        require_affiliate_payload("videos", payload)


def test_video_discriminator_accepts_video_without_play_info() -> None:
    performance = {
        "creator_base": {"oec_id": "creator-1", "handle_name": "@creator"},
        "product_base_list": [],
        "product_ids": [],
        "video_info": {"item_id": "video-1", "create_time": "1787616000000"},
        "video_metrics": {
            "video_gmv": {"amount": "0", "currency_code": "USD"},
            "video_orders_cnt": {"value": "0"},
            "video_product_impressions_cnt": {"value": "0"},
            "video_views_cnt": {"value": "0"},
        },
    }

    assert (
        require_affiliate_payload("videos", _video_payload([performance]))
        == "tiktok_affiliate_video_detail_list.v1"
    )


@pytest.mark.parametrize(
    ("resource", "payload"),
    [
        ("creators", _video_payload()),
        ("videos", _creator_payload()),
        ("creators", {"code": 0, "data": {"segments": []}}),
        (
            "videos",
            {
                "code": 0,
                "data": {
                    "video_list_segments_v2": [{"total": 1, "video_performances": []}]
                },
            },
        ),
    ],
)
def test_discriminator_rejects_wrong_or_lookalike_payload(
    resource: str, payload: object
) -> None:
    with pytest.raises(AffiliatePayloadDiscriminatorError):
        require_affiliate_payload(resource, payload)


@pytest.mark.parametrize(
    ("paths", "expected_mode"),
    [
        (
            {
                "data.next_pagination.has_more",
                "data.next_pagination.next_page",
                "data.next_pagination.total_page",
            },
            "page_page_size",
        ),
        ({"data.offset", "data.limit", "data.total"}, "offset"),
        ({"data.next_cursor", "data.has_more"}, "cursor"),
        ({"data.page", "data.page_size", "data.next_cursor"}, "mixed"),
        ({"data.total"}, "unknown"),
    ],
)
def test_pagination_mode_uses_only_observed_field_names(
    paths: set[str], expected_mode: str
) -> None:
    result = classify_pagination_mode(paths)

    assert result["mode"] == expected_mode
    assert result["basis"] == "observed_field_names"
    assert result["requestPaginationObserved"] is False
