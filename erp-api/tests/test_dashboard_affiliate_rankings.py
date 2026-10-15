from erp_api.services.dashboard_affiliate_rankings import build_rankings


def test_rankings_sort_videos_and_do_not_duplicate_product_video_counts() -> None:
    pages = [
        (
            "Shop A",
            [
                {
                    "videoId": "v1",
                    "title": "First",
                    "creatorUsername": "alice",
                    "gmvMinor": 300,
                    "itemsSold": 2,
                    "views": 20,
                    "promotedProducts": [
                        {"productId": "p1", "title": "Toy", "coverImageUrl": "cover"},
                        {"productId": "p1", "title": "Toy"},
                    ],
                },
                {
                    "videoId": "v2",
                    "title": "Second",
                    "gmvMinor": 500,
                    "itemsSold": 4,
                    "promotedProductIds": ["p1", "p2"],
                },
            ],
        )
    ]

    result = build_rankings(pages)

    assert [row["videoId"] for row in result["topVideos"]] == ["v2", "v1"]
    products = {row["productId"]: row for row in result["topProducts"]}
    assert products["p1"]["videoCount"] == 2
    assert products["p1"]["singleProductVideoGmvMinor"] == 300
    assert products["p1"]["singleProductVideoItemsSold"] == 2
    assert products["p2"]["singleProductVideoGmvMinor"] is None
    assert products["p2"]["singleProductVideoItemsSold"] is None


def test_video_gmv_is_not_allocated_to_promoted_products() -> None:
    result = build_rankings(
        [
            (
                "Shop A",
                [
                    {
                        "videoId": "v1",
                        "gmvMinor": 9999,
                        "promotedProductIds": ["p1", "p2"],
                    }
                ],
            )
        ]
    )

    assert all(
        row["singleProductVideoGmvMinor"] is None for row in result["topProducts"]
    )
