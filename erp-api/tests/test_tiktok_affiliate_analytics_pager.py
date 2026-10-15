import asyncio
import json

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import (
    CaptureGuardConfig,
)


class FakeItemLocator:
    def __init__(self, page: "FakePage", index: int) -> None:
        self._page = page
        self._index = index

    async def click(self) -> None:
        self._page.click_index(self._index)

    async def evaluate(self, script: str) -> None:
        assert script == "(element) => element.click()"
        self._page.click_index(self._index)

    async def is_visible(self) -> bool:
        return self._page.captcha


class FakePaginationLocator:
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    async def evaluate_all(self, script: str) -> list[dict[str, object]]:
        assert "fetch" not in script.casefold()
        return self._page.pagination_items()

    def nth(self, index: int) -> FakeItemLocator:
        return FakeItemLocator(self._page, index)

    async def count(self) -> int:
        return 1 if self._page.captcha else 0


class FakePage:
    def __init__(self, path: str, pages: list[int], active: int) -> None:
        self.url = (
            f"https://affiliate.tiktokshopglobalselling.com{path}?msToken=not-recorded"
        )
        self.pages = pages
        self.active = active
        self.clicked: list[int] = []
        self.captcha = False

    def locator(self, selector: str) -> FakePaginationLocator:
        assert selector in {
            ".kora-pagination-item",
            ".core-pagination-item",
            'iframe[src*="captcha" i], [id*="captcha" i], [class*="captcha" i]',
        }
        return FakePaginationLocator(self)

    def pagination_items(self) -> list[dict[str, object]]:
        return [
            {
                "text": str(number),
                "className": "pagination-item-active"
                if number == self.active
                else "pagination-item",
                "ariaCurrent": "true" if number == self.active else None,
                "ariaDisabled": None,
            }
            for number in self.pages
        ]

    def click_index(self, index: int) -> None:
        number = self.pages[index]
        self.clicked.append(number)
        self.active = number


def _observation(resource: str) -> dict[str, object]:
    if resource == "creators":
        return {
            "host": "affiliate.tiktokshopglobalselling.com",
            "method": "POST",
            "path": "/api/v2/insights/affiliate/seller/creator/filter_list",
            "payloadDiscriminator": "tiktok_affiliate_creator_filter_list.v1",
            "pagination": {"mode": "page_page_size"},
        }
    return {
        "host": "affiliate.tiktokshopglobalselling.com",
        "method": "POST",
        "path": "/api/v1/oec/affiliate/compass/transaction/detail_list/get",
        "payloadDiscriminator": "tiktok_affiliate_video_detail_list.v1",
        "pagination": {"mode": "unknown"},
    }


def _payload(page: FakePage, resource: str) -> dict[str, object]:
    if resource == "creators":
        return {
            "data": {
                "segments": [
                    {
                        "list_control": {
                            "next_pagination": {
                                "has_more": page.active < page.pages[-1],
                                "total": len(page.pages),
                            }
                        },
                        "timed_lists": [{"stats": [{"id": f"creator-{page.active}"}]}],
                    }
                ]
            }
        }
    return {
        "data": {
            "video_list_segments_v2": [
                {
                    "total": len(page.pages),
                    "video_performances": [
                        {"video_info": {"item_id": f"video-{page.active}"}}
                    ],
                }
            ]
        }
    }


def _pager(lock: asyncio.Lock) -> TikTokAffiliateAnalyticsPager:
    return TikTokAffiliateAnalyticsPager(
        lock,
        guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
        settle_delay_seconds=0,
        watchdog_interval_seconds=0,
    )


async def _capture(
    pager: TikTokAffiliateAnalyticsPager,
    lock: asyncio.Lock,
    page: FakePage,
    resource: str,
    response_context: AffiliateAnalyticsResponseContext | None = None,
) -> None:
    async with lock:
        await pager.handle_payload(
            page,  # type: ignore[arg-type]
            resource,
            _payload(page, resource),
            _observation(resource),
            response_context,
        )
    await pager.wait_for_pending()


def test_first_valid_response_captures_safe_template_and_clicks_next_page(
    capsys,
) -> None:
    async def run():
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", [1, 2, 3], 1)
        pager = _pager(lock)
        await _capture(pager, lock, page, "creators")
        return page.clicked, pager.request_templates, pager.auto_started_resources

    clicked, templates, started_resources = asyncio.run(run())

    assert clicked == [2]
    assert templates == {
        "creators": {
            "resource": "creators",
            "host": "affiliate.tiktokshopglobalselling.com",
            "method": "POST",
            "path": "/api/v2/insights/affiliate/seller/creator/filter_list",
            "pagePath": "/data/creator-analysis",
            "triggerMode": "page_control",
        }
    }
    assert started_resources == {"creators"}
    output = capsys.readouterr().out
    assert "affiliate_analytics_page_captured" in output
    assert "affiliate_analytics_page_advance_requested" in output
    assert "not-recorded" not in output
    for line in output.splitlines():
        assert set(json.loads(line)) <= {
            "timestamp",
            "event",
            "pages_fetched",
            "records_received",
            "records_unique",
            "duplicates",
            "expected_total",
        }


def test_direct_request_pager_does_not_depend_on_visible_page_buttons() -> None:
    async def run() -> list[int]:
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", [1, 2, 3], 1)
        current = 1
        requested = []

        async def request_page(page_number: int) -> None:
            nonlocal current
            current = page_number
            requested.append(page_number)

        pager = TikTokAffiliateAnalyticsPager(
            lock,
            guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
            settle_delay_seconds=0,
            watchdog_interval_seconds=0,
            page_requester=request_page,
            page_number_provider=lambda: current,
        )
        await _capture(pager, lock, page, "creators")
        return requested

    assert asyncio.run(run()) == [2]


def test_each_new_page_response_advances_at_most_once() -> None:
    async def run() -> list[int]:
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", [1, 2, 3], 1)
        pager = _pager(lock)
        await _capture(pager, lock, page, "creators")
        await _capture(pager, lock, page, "creators")
        await _capture(pager, lock, page, "creators")
        return page.clicked

    assert asyncio.run(run()) == [2, 3]


def test_last_visible_video_page_stops_without_guessing_mode(capsys) -> None:
    async def run() -> list[int]:
        lock = asyncio.Lock()
        page = FakePage("/affiliate/assets/video-analysis", [1, 2], 2)
        pager = _pager(lock)
        await _capture(pager, lock, page, "videos")
        return page.clicked

    assert asyncio.run(run()) == []
    output = capsys.readouterr().out
    assert "affiliate_analytics_resource_stopped" in output
    assert "pagination_mode" not in output
    assert "terminal_reason" not in output


def test_page_resource_mismatch_is_not_automated() -> None:
    async def run() -> tuple[list[int], dict[str, dict[str, str]]]:
        lock = asyncio.Lock()
        page = FakePage("/affiliate/assets/video-analysis", [1, 2], 1)
        pager = _pager(lock)
        await _capture(pager, lock, page, "creators")
        return page.clicked, pager.request_templates

    assert asyncio.run(run()) == ([], {})


def test_captcha_overlay_immediately_stops_only_creator_resource() -> None:
    async def run() -> dict[str, dict[str, object]]:
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", [1, 2], 1)
        page.captcha = True
        pager = _pager(lock)
        await _capture(pager, lock, page, "creators")
        return pager.resource_states

    states = asyncio.run(run())
    assert states["creators"]["status"] == "session_required"
    assert states["creators"]["failure_category"] == "captcha"
    assert states["videos"]["status"] == "idle"


def test_session_navigation_is_detected_by_watchdog() -> None:
    async def run() -> dict[str, dict[str, object]]:
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", [1, 2], 1)
        pager = TikTokAffiliateAnalyticsPager(
            lock,
            guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
            settle_delay_seconds=0,
            watchdog_interval_seconds=0.01,
        )
        await _capture(pager, lock, page, "creators")
        page.url = "https://affiliate.tiktokshopglobalselling.com/login"
        await asyncio.sleep(0.03)
        states = pager.resource_states
        await pager.stop()
        return states

    states = asyncio.run(run())
    assert states["creators"]["status"] == "partial"
    assert states["creators"]["failure_category"] == "page_failed"
    assert states["videos"]["status"] == "idle"


def test_failed_creator_does_not_retry_or_stop_video_resource() -> None:
    async def run():
        lock = asyncio.Lock()
        creator_page = FakePage("/data/creator-analysis", [1, 2], 1)
        video_page = FakePage("/affiliate/assets/video-analysis", [1, 2], 1)
        pager = _pager(lock)
        async with lock:
            await pager.handle_failure(
                creator_page,  # type: ignore[arg-type]
                "creators",
                "failed",
                "http_403",
            )
        await _capture(pager, lock, creator_page, "creators")
        await _capture(pager, lock, video_page, "videos")
        return creator_page.clicked, video_page.clicked, pager.resource_states

    creator_clicks, video_clicks, states = asyncio.run(run())
    assert creator_clicks == []
    assert video_clicks == [2]
    assert states["creators"]["failure_category"] == "http_403"
    assert states["videos"]["status"] == "running"
