from collections.abc import Mapping
from urllib.parse import urlsplit

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_analytics_page_evidence import page_records


def is_direct_video_total_boundary(
    resource: str,
    current_page: int,
    payload: Mapping[str, object],
    snapshot: Mapping[str, object],
    context: AffiliateAnalyticsResponseContext | None,
) -> bool:
    if resource != "videos" or context is None:
        return False
    if urlsplit(context.request_url or "").hostname != "affiliate-us.tiktok.com":
        return False
    try:
        body = context.request_body
        assert isinstance(body, Mapping)
        segment = body["params"]["video_list_params_v2"][0]
        page_param = segment["page_param"]
        page_number = page_param["page_no"]
        page_size = page_param["page_size"]
    except (AssertionError, KeyError, IndexError, TypeError):
        return False
    expected = snapshot.get("expected_total")
    actual = snapshot.get("records_unique")
    rows, _, page_total = page_records("videos", payload)
    return (
        isinstance(page_number, int)
        and not isinstance(page_number, bool)
        and page_number == current_page
        and isinstance(page_size, int)
        and not isinstance(page_size, bool)
        and page_size > 0
        and isinstance(expected, int)
        and not isinstance(expected, bool)
        and expected > 0
        and page_total == expected
        and isinstance(actual, int)
        and actual < expected
        and snapshot.get("duplicates") == 0
        and snapshot.get("records_received") == actual
        and snapshot.get("first_page_index") == 1
        and snapshot.get("last_page_index") == current_page
        and snapshot.get("pages_fetched") == current_page
        and current_page == (expected + page_size - 1) // page_size
        and 0 < rows < page_size
    )
