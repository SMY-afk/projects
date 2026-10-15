from backend.app.services.tiktok_affiliate_intent_priority import (
    intent_timeout_seconds,
)


def test_video_capture_allows_time_for_reverse_page_and_export_verification() -> None:
    assert intent_timeout_seconds("videos") == 1830.0
    assert intent_timeout_seconds("liveAccounts") == 930.0
