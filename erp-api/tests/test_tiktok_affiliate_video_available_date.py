import asyncio
from datetime import UTC, date, datetime

import pytest

from backend.app.services import tiktok_affiliate_available_date as available_date
from backend.app.services.tiktok_affiliate_video_available_date import (
    VIDEO_MODULE_TYPES,
    video_day_from_available_ranges,
)


def _timestamp(day: int) -> int:
    return int(datetime(2026, 10, day, 8, tzinfo=UTC).timestamp())


def _response(*, missing: bool = False) -> dict:
    rows = [
        {
            "module_type": module,
            "start_time": _timestamp(1) - 30 * 86_400,
            "end_time": _timestamp(1 if module == 104 else 3),
            "timezone_offset": -28_800,
        }
        for module in sorted(VIDEO_MODULE_TYPES)
    ]
    return {
        "code": 0,
        "data": {"available_time_range_list": rows[:-1] if missing else rows},
    }


def test_video_date_uses_exclusive_common_end_across_every_module() -> None:
    assert video_day_from_available_ranges(
        {"module_types": sorted(VIDEO_MODULE_TYPES)}, _response()
    ) == date(2026, 9, 30)


@pytest.mark.parametrize(
    "request_data,response_data",
    [
        ({"module_types": sorted(VIDEO_MODULE_TYPES)}, _response(missing=True)),
        ({"module_types": sorted(VIDEO_MODULE_TYPES)}, {**_response(), "code": 401}),
        ({"module_types": sorted(VIDEO_MODULE_TYPES) + [104]}, _response()),
        ({"module_types": sorted(VIDEO_MODULE_TYPES - {104}) + [105]}, _response()),
    ],
)
def test_video_date_rejects_incomplete_or_invalid_modules(
    request_data, response_data
) -> None:
    assert video_day_from_available_ranges(request_data, response_data) is None


def test_video_date_rejects_empty_common_window() -> None:
    payload = _response()
    payload["data"]["available_time_range_list"][0]["start_time"] = _timestamp(1)
    assert (
        video_day_from_available_ranges(
            {"module_types": sorted(VIDEO_MODULE_TYPES)}, payload
        )
        is None
    )


@pytest.mark.parametrize(
    "host", ["affiliate.tiktokshopglobalselling.com", "affiliate-us.tiktok.com"]
)
def test_current_video_page_uses_authoritative_api_probe(monkeypatch, host) -> None:
    class Page:
        url = (
            f"https://{host}/insights/video-analysis"
            "?shop_region=US&shop_id=9121478993551097445"
        )

    class Context:
        def __init__(self):
            self.pages = [Page()]

    async def probe(context, url):
        assert context is source
        assert "shop_id=9121478993551097445" in url
        return date(2026, 9, 30)

    source = Context()
    monkeypatch.setattr(available_date, "detect_video_api_latest_day", probe)
    assert asyncio.run(
        available_date._detect_resource_date([source], "videos")
    ) == date(2026, 9, 30)
