from datetime import UTC, datetime

from erp_api.services.sample_creator_profile import normalize_creator_profile


def test_profile_normalizes_safe_avatar_and_optional_detail_sections() -> None:
    observed_at = datetime(2026, 9, 10, 8, tzinfo=UTC)
    result = normalize_creator_profile(
        {
            "avatar_object_key": "sample/creator-avatars/t/s/c/hash.jpg",
            "avatar_source_hash": "a" * 64,
            "performance": {
                "bio_description": "Lifestyle creator",
                "selection_region": "Virginia",
                "creator_categories": [
                    {"id": "textile", "label": "Textiles & Soft Furnishings"}
                ],
                "rating_count": 4,
                "pps_band": "Medium",
                "pps_description": "Good creator performance",
                "gpm": "6.4",
                "video_gpm": "5.2",
                "video_gmv": {"amount": "8300"},
                "ec_video_count": 28,
                "avg_ec_video_play_count": 12500,
                "ec_video_engagement_rate": "735",
                "live_gpm": "1.1",
                "live_gmv": {"amount": "200"},
                "ec_live_count": 3,
                "ec_live_engagement_rate": "280",
                "avg_gmv_per_buyer": "54.2",
                "post_rate": "9735",
                "avg_commission_rate": "1000",
                "promoted_product_num": 16,
                "brand_collaboration_count": 52,
                "category_gmv_distribution": [
                    {"category_name": "Textiles", "revenue_percentage": "90.37"}
                ],
                "content_gmv_distribution": {"Video": "100"},
                "sales_window": {
                    "start_at": "2026-08-08T00:00:00-07:00",
                    "end_at": "2026-09-07T23:59:59-07:00",
                    "timezone": "GMT-7",
                },
                "sample_score": {
                    "overall": "86",
                    "content_effect": "90",
                    "content_effect_percentile_bps": 8900,
                    "posting_freshness": "85",
                    "posting_freshness_percentile_bps": 8100,
                    "selling_power": "80",
                    "selling_power_percentile_bps": 8000,
                    "posting_effect": "94",
                    "posting_effect_percentile_bps": 9200,
                },
                "trends": {
                    "gmv": {"amount": "8500"},
                    "units_sold": 167,
                    "followers": 741000,
                    "video_views": 350000,
                    "engagement_rate_bps": "735",
                },
                "follower_demographics": {
                    "gender": {"Female": "73.61", "Male": "26.39"},
                    "age": [{"range": "45-54", "percentage": "38.2"}],
                    "top_regions": [{"region": "Texas", "percentage": "8.3"}],
                },
            },
        },
        observed_at=observed_at,
        source_type="official_api",
    )

    assert result["creator_avatar_object_key"].endswith("hash.jpg")
    assert result["creator_avatar_source_hash"] == "a" * 64
    assert result["creator_avatar_observed_at"] == observed_at
    snapshot = result["creator_profile_snapshot"]
    assert snapshot["schema_version"] == 2
    assert snapshot["sales"]["gmv_per_mille_minor"] == 640
    assert snapshot["cooperation"]["estimated_post_rate_bps"] == 9735
    assert snapshot["sales"]["category_shares"][0]["share_bps"] == 9037
    assert snapshot["sales"]["window"]["timezone"] == "GMT-7"
    assert snapshot["creator_categories"][0]["label"].startswith("Textiles")
    assert snapshot["rating_count"] == 4
    assert snapshot["pps"] == {
        "band_code": "MEDIUM",
        "band_label": "中等",
        "description": "Good creator performance",
    }
    assert snapshot["sample_score"]["content_effect_percentile_bps"] == 8900
    assert snapshot["video"] == {
        "gmv_minor": 830000,
        "gmv_per_mille_minor": 520,
        "count": 28,
        "average_view_count": 12500,
        "average_engagement_rate_bps": 735,
    }
    assert snapshot["live"] == {
        "gmv_minor": 20000,
        "gmv_per_mille_minor": 110,
        "count": 3,
        "average_engagement_rate_bps": 280,
    }
    assert snapshot["trends"]["gmv_minor"] == 850000
    assert snapshot["audience"]["gender"][0] == {
        "code": "Female",
        "label": "Female",
        "share_bps": 7361,
    }


def test_profile_ignores_signed_avatar_url_and_omits_missing_snapshot() -> None:
    result = normalize_creator_profile(
        {
            "avatar_url": "https://cdn.test/a.jpg?refresh_token=private",
            "username": "creator",
        },
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        source_type="official_api",
    )

    assert result == {}
