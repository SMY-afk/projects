from erp_api.services.media_image_repository import (
    extract_product_images,
    extract_video_covers,
)


def test_extracts_product_images_from_seller_product_analytics() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "meta": {
                        "product_id": "product-1",
                        "product_image": "https://cdn.example/product-1.jpg",
                    }
                }
            ]
        }
    }

    assert extract_product_images("seller_product_analytics", payload) == {
        "product-1": "https://cdn.example/product-1.jpg"
    }


def test_extracts_product_images_from_seller_product_catalog() -> None:
    payload = {
        "data": {
            "products": [
                {
                    "product_id": "product-1",
                    "image": {
                        "uri": "tos-maliva-i-o3syd03w52-us/product-1",
                        "url_list": ["https://cdn.example/product-1.jpg"],
                    },
                }
            ]
        }
    }

    assert extract_product_images("seller_product_catalog", payload) == {
        "product-1": "https://cdn.example/product-1.jpg"
    }


def test_extracts_video_cover_and_promoted_product_image() -> None:
    payload = {
        "data": {
            "segments": [
                {
                    "timed_lists": [
                        {
                            "stats": [
                                {
                                    "video_meta": {
                                        "id": "video-1",
                                        "cover_image": {
                                            "thumb_url_list": [
                                                "https://cdn.example/video-1.jpg"
                                            ]
                                        },
                                    },
                                    "product_list": [
                                        {
                                            "product_id": "product-1",
                                            "product_image": {
                                                "thumb_uri": "https://cdn.example/product-1.jpg"
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }

    assert extract_video_covers(payload) == {
        "video-1": "https://cdn.example/video-1.jpg"
    }
    assert extract_product_images("seller_video_analytics", payload) == {
        "product-1": "https://cdn.example/product-1.jpg"
    }


def test_extracts_affiliate_product_url_list() -> None:
    payload = {
        "sku_order_base_info_for_affiliate_seller": {
            "product_info": {
                "product_id": "product-1",
                "image_uri": "not-a-public-url",
                "url_list": ["https://cdn.example/product-1.jpg"],
            }
        }
    }

    assert extract_product_images("affiliate_order", payload) == {
        "product-1": "https://cdn.example/product-1.jpg"
    }
