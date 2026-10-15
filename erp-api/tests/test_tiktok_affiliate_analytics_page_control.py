from types import SimpleNamespace

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_PAGE,
    matches_page,
)


def test_video_page_matches_us_insights_route() -> None:
    page = SimpleNamespace(
        url="https://affiliate-us.tiktok.com/insights/video-analysis?shop_id=123"
    )

    assert matches_page(page, RESOURCE_PAGE["videos"][0])


def test_video_page_rejects_unrelated_host_or_path() -> None:
    path = RESOURCE_PAGE["videos"][0]

    assert not matches_page(
        SimpleNamespace(url="https://example.test/insights/video-analysis"), path
    )
    assert not matches_page(
        SimpleNamespace(url="https://affiliate-us.tiktok.com/insights/other"), path
    )
