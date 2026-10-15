from erp_api.services.affiliate_video_media_enrichment import merge_video_media


def test_video_list_uses_the_repaired_avatar_instead_of_an_expired_snapshot():
    cached = "https://example.invalid/configure-resource" + "a" * 64 + ".jpg"
    item = {"id": "video-1", "creatorUsername": "@Creator_Name",
            "creatorAvatarUrl": "https://p16-sign.tiktokcdn-us.com/old.jpg?x-expires=1",
            "revenueMinor": 12345}
    merged = merge_video_media(item, avatars_by_username={"creator_name": cached},
        avatars_by_open_id={}, products_by_id={}, product_images={}, video_covers={})
    assert merged["creatorAvatarUrl"] == cached
    assert merged["revenueMinor"] == item["revenueMinor"]
    assert item["creatorAvatarUrl"].endswith("x-expires=1")


def test_merge_video_media_fills_avatar_cover_and_product_cards() -> None:
    item = {
        "id": "video-1",
        "videoId": "video-1",
        "creatorUsername": "@Creator_Name",
        "creatorOpenId": "open-1",
        "creatorAvatarUrl": None,
        "coverImageUrl": None,
        "promotedProductIds": ["product-1"],
        "promotedProducts": [],
    }

    merged = merge_video_media(
        item,
        avatars_by_username={"creator_name": "https://img.test/avatar.jpg"},
        avatars_by_open_id={},
        products_by_id={"product-1": "Remote control car"},
        product_images={"product-1": "https://img.test/product.jpg"},
        video_covers={"video-1": "https://img.test/video.jpg"},
    )

    assert merged["creatorAvatarUrl"] == "https://img.test/avatar.jpg"
    assert merged["coverImageUrl"] == "https://img.test/video.jpg"
    assert merged["promotedProducts"] == [
        {
            "productId": "product-1",
            "title": "Remote control car",
            "coverImageUrl": "https://img.test/product.jpg",
        }
    ]


def test_merge_video_media_keeps_richer_captured_values() -> None:
    item = {
        "id": "video-1",
        "creatorUsername": "creator",
        "creatorAvatarUrl": "https://captured.test/avatar.jpg",
        "coverImageUrl": "https://captured.test/video.jpg",
        "promotedProducts": [
            {
                "productId": "product-1",
                "title": "Captured title",
                "coverImageUrl": "https://captured.test/product.jpg",
            }
        ],
    }

    merged = merge_video_media(
        item,
        avatars_by_username={"creator": "https://fallback.test/avatar.jpg"},
        avatars_by_open_id={},
        products_by_id={"product-1": "Fallback title"},
        product_images={"product-1": "https://fallback.test/product.jpg"},
        video_covers={"video-1": "https://fallback.test/video.jpg"},
    )

    assert merged["creatorAvatarUrl"] == "https://captured.test/avatar.jpg"
    assert merged["coverImageUrl"] == "https://captured.test/video.jpg"
    assert merged["promotedProducts"][0] == item["promotedProducts"][0]


def test_merge_video_media_prefers_fresh_stored_cover_url() -> None:
    item = {
        "id": "video-1",
        "coverImageUrl": "https://expired.test/video.jpg",
        "coverImageObjectKey": "affiliate/video-covers/video-1",
    }

    merged = merge_video_media(
        item,
        avatars_by_username={},
        avatars_by_open_id={},
        products_by_id={},
        product_images={},
        video_covers={"video-1": "https://storage.test/fresh.jpg"},
    )

    assert merged["coverImageUrl"] == "https://storage.test/fresh.jpg"
