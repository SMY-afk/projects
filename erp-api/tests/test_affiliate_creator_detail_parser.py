from erp_api.services.affiliate_creator_detail_parser import (
    discriminate_creator_detail,
    parse_creator_detail_page,
)


def _payload():
    return {
        "data": {
            "segments": [
                {
                    "time_descriptor": {
                        "start": 1787529600,
                        "end": 1788134400,
                    },
                    "list_control": {
                        "next_pagination": {
                            "has_more": True,
                            "next_page": 2,
                            "total": 3,
                            "total_page": 2,
                        }
                    },
                    "timed_lists": [
                        {
                            "stats": [
                                {
                                    "product_meta": {
                                        "id": "product-1",
                                        "name": "RC Truck",
                                        "cover_image": {
                                            "thumb_url_list": ["https://img.test/1"]
                                        },
                                    },
                                    "gmv": {
                                        "amount": "12.34",
                                        "currency_code": "USD",
                                    },
                                    "item_sold_cnt": "2",
                                    "product_ctr": "0.125",
                                    "future_metric": "kept",
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }


def _request(*, only_sample=True):
    filters = {"creator_id": "creator-private", "shop_id": "shop-platform"}
    if only_sample:
        filters["only_sample"] = True
    return {"filter": filters, "pagination": {"page": 1, "page_size": 20}}


def test_product_and_product_card_share_path_but_have_strict_discriminator():
    path = "/api/v2/insights/affiliate/seller/creator_analytics/creator/product/list"

    assert discriminate_creator_detail(path, _request()) == "product"
    assert (
        discriminate_creator_detail(path, _request(only_sample=False)) == "product_card"
    )


def test_parse_creator_product_page_normalizes_money_ratio_and_pagination():
    page = parse_creator_detail_page("product", _payload(), _request(), "USD")

    assert page.platform_creator_id == "creator-private"
    assert page.page_number == 1
    assert page.has_more is True
    assert page.next_page == 2
    assert page.total_count == 3
    assert page.records[0].identity == {
        "productId": "product-1",
        "title": "RC Truck",
        "coverImageUrl": "https://img.test/1",
    }
    assert page.records[0].metrics["gmvMinor"] == 1234
    assert page.records[0].metrics["itemsSold"] == 2
    assert page.records[0].metrics["productClickThroughRate"] == "0.125"
    assert page.records[0].extensions == {"future_metric": "kept"}


def test_detail_discriminator_rejects_search_and_unrelated_paths():
    assert (
        discriminate_creator_detail(
            "/api/v2/insights/affiliate/seller/creator_analytics/creator/video/search/list",
            _request(),
        )
        is None
    )
