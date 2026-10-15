from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.affiliate_creator_summary_parser import (
    CreatorSummaryPayload,
    discriminate_creator_summary,
    merge_profile_snapshots,
    parse_creator_summary,
    validate_creator_summary_identity,
)
from erp_api.services.affiliate_creator_summary_repository import _updated_extensions


def _request():
    return {"request": {"creator_id": "page-creator-1"}}


@pytest.mark.parametrize(
    ("path", "kind"),
    (
        (
            "/api/v2/oec/affiliate/creator/marketplace/profile",
            "profile",
        ),
        (
            "/api/v2/oec/affiliate/creator/marketplace/creator/profile/stats",
            "collaboration",
        ),
        ("/api/v2/oec/affiliate/cmp/creator/ec/stats", "sales"),
        (
            "/api/v2/oec/affiliate/creator/marketplace/content/stats",
            "content",
        ),
        (
            "/api/v2/oec/affiliate/creator/marketplace/follower/stats",
            "followers",
        ),
    ),
)
def test_discriminates_real_creator_details_summary_paths(path, kind):
    assert discriminate_creator_summary(path) == kind


def test_rejects_detail_lists_and_lookalike_paths():
    assert (
        discriminate_creator_summary(
            "/api/v2/insights/affiliate/seller/creator_analytics/creator/video/list"
        )
        is None
    )
    assert (
        discriminate_creator_summary(
            "/api/v2/oec/affiliate/creator/marketplace/profile/export"
        )
        is None
    )


def test_parses_sales_summary_and_normalizes_identity_and_profile():
    summary = parse_creator_summary(
        "sales",
        {
            "data": {
                "creator": {
                    "creator_open_id": "open-1",
                    "username": "@LetsBeHayleyWhite",
                },
                "gmv": {"amount": "544", "currency_code": "USD"},
                "units_sold": 23,
                "gpm": {"amount": "12.2", "currency_code": "USD"},
                "avg_gmv_per_buyer": {"amount": "23.6"},
                "content_gmv_distribution": {"Video": "100"},
            }
        },
        _request(),
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert summary.platform_creator_id == "page-creator-1"
    assert summary.creator_open_id == "open-1"
    assert summary.creator_username == "LetsBeHayleyWhite"
    assert summary.profile_snapshot["sales"] == {
        "gmv_minor": 54_400,
        "units_sold": 23,
        "gmv_per_mille_minor": 1_220,
        "average_order_value_minor": 2_360,
        "channel_shares": [{"code": "video", "label": "video", "share_bps": 10_000}],
    }


def test_content_summary_persists_video_live_and_trends_sections():
    summary = parse_creator_summary(
        "content",
        {
            "data": {
                "video": {
                    "video_gpm": "13.6",
                    "ec_video_count": 111,
                    "avg_ec_video_play_count": 331,
                    "ec_video_engagement_rate": "1127",
                },
                "live": {
                    "live_gpm": "0",
                    "ec_live_count": 12,
                    "avg_ec_live_play_count": 857,
                    "ec_live_engagement_rate": "9876",
                },
                "trends": {"gmv": "544", "units_sold": 23},
            }
        },
        _request(),
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert summary.profile_snapshot["video"]["count"] == 111
    assert summary.profile_snapshot["video"]["average_view_count"] == 331
    assert summary.profile_snapshot["live"]["count"] == 12
    assert summary.profile_snapshot["live"]["average_view_count"] == 857
    assert summary.profile_snapshot["trends"]["units_sold"] == 23


def test_triple_identity_validation_fails_closed():
    validate_creator_summary_identity(
        expected_open_id="open-1",
        expected_username="letsbehayleywhite",
        expected_shop_id="shop-1",
        actual_open_id="open-1",
        actual_username="@LetsBeHayleyWhite",
        actual_shop_id="shop-1",
    )

    with pytest.raises(ValueError, match="creator_open_id"):
        validate_creator_summary_identity(
            expected_open_id="open-1",
            expected_username="letsbehayleywhite",
            expected_shop_id="shop-1",
            actual_open_id="open-2",
            actual_username="letsbehayleywhite",
            actual_shop_id="shop-1",
        )


def test_profile_snapshots_merge_recursively_without_dropping_prior_data():
    merged = merge_profile_snapshots(
        {"schema_version": 2, "sales": {"gmv_minor": 100, "units_sold": 2}},
        {"schema_version": 2, "sales": {"gmv_minor": 200}, "video": {"count": 3}},
    )

    assert merged == {
        "schema_version": 2,
        "sales": {"gmv_minor": 200, "units_sold": 2},
        "video": {"count": 3},
    }


def test_persistence_shape_keeps_six_sections_and_sanitized_source_payloads():
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    summary = CreatorSummaryPayload(
        resource_kind="content",
        platform_creator_id="page-1",
        creator_open_id="open-1",
        creator_username="creator",
        profile_snapshot={
            "schema_version": 2,
            "sales": {"gmv_minor": 1},
            "cooperation": {"product_count": 2},
            "video": {"count": 3},
            "live": {"count": 4},
            "audience": {"gender": [{"label": "Female", "share_bps": 7500}]},
            "trends": {"units_sold": 5},
        },
        raw_data={"content": {"safe": True}},
        observed_at=observed_at,
    )

    extensions = _updated_extensions(
        {},
        summary,
        shop_id=uuid4(),
        open_id="open-1",
        username="creator",
        request_id="request-1",
        response_path="/api/v2/content/stats",
    )

    details = extensions["creator_details_summary"]
    assert set(details["sections"]) == {
        "sales",
        "collaboration",
        "video",
        "live",
        "followers",
        "trends",
    }
    assert details["source_payloads"]["content"] == {"content": {"safe": True}}
