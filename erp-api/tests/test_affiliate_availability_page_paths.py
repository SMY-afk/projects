from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from backend.app.services.tiktok_affiliate_available_date import _resource_url


def test_availability_uses_global_video_analytics_page():
    context = SimpleNamespace(
        pages=[
            SimpleNamespace(
                url="https://affiliate.tiktokshopglobalselling.com/data/creator-analysis?shop_id=123"
            )
        ]
    )
    url = _resource_url([context], "videos")
    assert urlsplit(url).path == "/insights/video-analysis"
    assert parse_qs(urlsplit(url).query)["shop_id"] == ["123"]


def test_availability_keeps_us_video_route():
    context = SimpleNamespace(
        pages=[
            SimpleNamespace(
                url="https://affiliate-us.tiktok.com/data/creator-analysis?shop_id=123&shop_region=US"
            )
        ]
    )
    url = _resource_url([context], "videos")
    assert urlsplit(url).path == "/insights/video-analysis"
    assert parse_qs(urlsplit(url).query)["shop_region"] == ["US"]
