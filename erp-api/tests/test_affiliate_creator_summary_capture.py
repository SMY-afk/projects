from backend.app.services.tiktok_affiliate_creator_summary_capture import (
    _page_creator_username,
)


def test_reads_creator_username_only_from_the_sample_request_detail_page_url() -> None:
    assert (
        _page_creator_username(
            "https://affiliate-us.tiktok.com/affiliate/creator/detail"
            "?cid=creator-id&cname=%40LetsBeHayleyWhite&shop_id=shop-id"
        )
        == "LetsBeHayleyWhite"
    )
    assert _page_creator_username("https://example.com/detail?cid=creator-id") is None
