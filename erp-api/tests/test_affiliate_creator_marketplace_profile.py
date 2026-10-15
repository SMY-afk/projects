from datetime import UTC, datetime

from erp_api.services.affiliate_creator_summary_parser import parse_creator_summary

OBSERVED_AT = datetime(2026, 9, 11, tzinfo=UTC)


def _field(value):
    return {"value": value, "is_authorized": True, "status": 1}


def _request(profile_type: int):
    return {"creator_oec_id": "page-creator-1", "profile_types": [profile_type]}


def test_parses_sample_request_creator_detail_identity_profile() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "code": 0,
            "creator_profile": {
                "creator_oecuid": _field("different-from-sample-open-id"),
                "handle": _field("@LetsBeHayleyWhite"),
                "bio": _field("Creator bio"),
                "selection_region": _field("Virginia"),
                "follower_cnt": _field("5969"),
                "category": _field(
                    [{"starling_key": "toys", "name": "Toys & Hobbies"}]
                ),
                "creator_fulfillment_reviews": _field(16),
            },
        },
        _request(1),
        observed_at=OBSERVED_AT,
    )

    assert summary.resource_kind == "profile"
    assert summary.platform_creator_id == "page-creator-1"
    assert summary.creator_open_id is None
    assert summary.creator_username == "LetsBeHayleyWhite"
    assert summary.profile_snapshot["bio"] == "Creator bio"
    assert summary.profile_snapshot["location"] == "Virginia"
    assert summary.profile_snapshot["follower_count"] == 5969
    assert summary.profile_snapshot["rating_count"] == 16
    assert summary.profile_snapshot["creator_categories"] == [
        {"id": "toys", "label": "Toys & Hobbies"}
    ]


def test_parses_creator_detail_performance_into_card_sections() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "code": 0,
            "creator_profile": {
                "med_gmv_revenue": _field(
                    {"value": "544", "symbol": "$", "format": "$544"}
                ),
                "units_sold": _field("23"),
                "gpm": _field({"value": "12.2", "symbol": "$", "format": "$12.2"}),
                "avg_revenue_per_buyer": _field(
                    {"value": "23.6", "symbol": "$", "format": "$23.6"}
                ),
                "sample_fulfillment_rate": _field(9589),
                "med_commission_rate": _field(1250),
                "promoted_product_num": _field("7"),
                "collaborated_brands_num": _field(93),
                "partnered_brand": _field([{"id": "b1", "name": "Brand"}]),
                "video_gmv": _field({"value": "544", "symbol": "$", "format": "$544"}),
                "ec_video_gpm": _field(
                    {
                        "minimal": "13.6",
                        "maximum": "13.6",
                        "symbol": "$",
                    }
                ),
                "video_publish_cnt_30d": _field("71"),
                "video_play_cnt_med": _field("297"),
                "video_engagement": _field(851),
                "ec_video_publish_cnt_30d": _field("111"),
                "ec_video_play_cnt_med": _field("331"),
                "ec_video_engagement": _field(1127),
                "live_gmv": _field({"value": "0", "symbol": "$", "format": "$0"}),
                "ec_live_gpm": _field(
                    {"minimal": "0", "maximum": "0", "symbol": "$"}
                ),
                "live_streaming_cnt_30d": _field("12"),
                "live_med_view_cnt": _field("857"),
                "live_engagement": _field(9876),
                "ec_live_streaming_cnt_30d": _field("99"),
                "ec_live_med_view_cnt": _field("999"),
                "ec_live_engagement": _field(9999),
                "pps_score": _field("3.9"),
                "sample_credit_total_score": _field(82),
                "sample_credit_fulfillment_score": _field(80),
                "sample_credit_fulfillment_rank": _field(78),
                "sample_credit_diligence_score": _field(80),
                "sample_credit_diligence_rank": _field(74),
                "sample_credit_sales_ability_score": _field(88),
                "sample_credit_sales_ability_rank": _field(89),
                "sample_credit_content_quality_score": _field(80),
                "sample_credit_content_quality_rank": _field(79),
            },
        },
        _request(2),
        observed_at=OBSERVED_AT,
    )

    assert summary.resource_kind == "performance"
    assert summary.profile_snapshot["sales"] == {
        "gmv_minor": 54_400,
        "units_sold": 23,
        "gmv_per_mille_minor": 1_220,
        "average_order_value_minor": 2_360,
        "window": {"kind": "last_30_days"},
    }
    assert summary.profile_snapshot["cooperation"] == {
        "estimated_post_rate_bps": 9589,
        "average_commission_rate_bps": 1250,
        "product_count": 7,
        "brand_collaboration_count": 93,
        "top_brand_ids": ["b1"],
    }
    assert summary.profile_snapshot["video"]["count"] == 71
    assert summary.profile_snapshot["video"]["average_view_count"] == 297
    assert summary.profile_snapshot["video"]["average_engagement_rate_bps"] == 851
    assert summary.profile_snapshot["video"]["gmv_per_mille_minor"] == 1360
    assert summary.profile_snapshot["live"]["count"] == 12
    assert summary.profile_snapshot["live"]["average_view_count"] == 857
    assert summary.profile_snapshot["pps"]["score"] == "3.9"
    assert summary.profile_snapshot["sample_score"]["overall"] == "82.00"
    assert (
        summary.profile_snapshot["sample_score"]["selling_power_percentile_bps"] == 8900
    )


def test_missing_performance_values_stay_missing_and_explicit_zero_is_kept() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "creator_profile": {
                "pps_score": _field("3.9"),
                "live_gmv": _field({"value": "0", "symbol": "$", "format": "$0"}),
            }
        },
        _request(2),
        observed_at=OBSERVED_AT,
    )

    assert summary.profile_snapshot["pps"] == {"score": "3.9"}
    assert summary.profile_snapshot["live"]["gmv_minor"] == 0
    assert "gmv_minor" not in summary.profile_snapshot["sales"]
    assert "count" not in summary.profile_snapshot["video"]


def test_does_not_invent_video_gpm_from_a_range() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "creator_profile": {
                "ec_video_gpm": _field(
                    {"minimal": "10", "maximum": "20", "symbol": "$"}
                )
            }
        },
        _request(2),
        observed_at=OBSERVED_AT,
    )

    assert "gmv_per_mille_minor" not in summary.profile_snapshot["video"]


def test_parses_creator_detail_followers_and_trends() -> None:
    followers = parse_creator_summary(
        "profile",
        {
            "creator_profile": {
                "follower_genders_v2": _field([{"key": "Female", "value": "75.02"}]),
                "follower_ages_v2": _field([{"key": "25-34", "value": "34.3"}]),
                "follower_state_location": _field([{"key": "Texas", "value": "12.5"}]),
            }
        },
        _request(3),
        observed_at=OBSERVED_AT,
    )
    trends = parse_creator_summary(
        "profile",
        {
            "creator_profile_trend_data": [
                {
                    "start_timestamp": 1788739200,
                    "end_timestamp": 1788825600,
                    "profile": {
                        "trend_gmv": _field(
                            {"value": "12.5", "symbol": "$", "format": "$12.5"}
                        ),
                        "trend_units_sold": _field("2"),
                        "trend_follower": _field("7508"),
                        "trend_video_play_cnt": _field("100"),
                        "trend_video_engagement_rate": _field(1100),
                    },
                }
            ]
        },
        _request(4),
        observed_at=OBSERVED_AT,
    )

    assert followers.resource_kind == "followers"
    assert followers.profile_snapshot["audience"]["gender"][0]["share_bps"] == 7502
    assert followers.profile_snapshot["audience"]["top_regions"][0]["label"] == "Texas"
    assert trends.resource_kind == "trends"
    assert trends.profile_snapshot["trends"]["gmv_minor"] == 1250
    assert trends.profile_snapshot["trends"]["units_sold"] == 2
    assert trends.profile_snapshot["trends"]["followers"] == 7508
    assert len(trends.profile_snapshot["trends"]["series"]) == 1


def test_followers_match_creator_details_display_units_and_order() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "creator_profile": {
                "follower_genders_v2": _field(
                    [
                        {"key": "male", "value": "0.1678"},
                        {"key": "female", "value": "0.7332"},
                    ]
                ),
                "follower_ages_v2": _field(
                    [
                        {"key": "35-44", "value": "0.4043"},
                        {"key": "18-24", "value": "0.0448"},
                        {"key": "25-34", "value": "0.3371"},
                        {"key": "45-54", "value": "0.1704"},
                        {"key": "55+", "value": "0.0431"},
                    ]
                ),
                "follower_state_location": _field(
                    [
                        {"key": "TEXAS", "value": "1264"},
                        {"key": "CALIFORNIA", "value": "1181"},
                    ]
                ),
            }
        },
        _request(3),
        observed_at=OBSERVED_AT,
    )

    audience = summary.profile_snapshot["audience"]
    assert audience["gender"] == [
        {"code": "male", "label": "Male", "share_bps": 1862},
        {"code": "female", "label": "Female", "share_bps": 8138},
    ]
    assert [item["code"] for item in audience["age"]] == [
        "18-24",
        "25-34",
        "35-44",
        "45-54",
        "55+",
    ]
    assert [item["share_bps"] for item in audience["age"]] == [
        450,
        3370,
        4050,
        1700,
        430,
    ]
    assert audience["top_regions"] == [
        {"code": "TEXAS", "label": "TEXAS", "share_bps": 1264},
        {"code": "CALIFORNIA", "label": "CALIFORNIA", "share_bps": 1181},
    ]


def test_keeps_example_videos_from_the_same_creator_details_page() -> None:
    summary = parse_creator_summary(
        "profile",
        {
            "creator_profile": {
                "top_video_data": _field(
                    [
                        {
                            "item_id": "video-1",
                            "name": "Example",
                            "play_cnt": 1000,
                            "like_cnt": 50,
                            "comment_cnt": 4,
                        }
                    ]
                )
            }
        },
        _request(5),
        observed_at=OBSERVED_AT,
    )

    assert summary.resource_kind == "examples"
    assert summary.profile_snapshot["example_videos"][0]["play_count"] == 1000
