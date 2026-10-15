import asyncio
import inspect
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
from backend.app.services.tiktok_affiliate_paging_driver import (
    AffiliatePagingDriver,
)


class FakeItemLocator:
    def __init__(self, page: "FakePage", index: int) -> None:
        self._page = page
        self._index = index

    async def click(self) -> None:
        raise AssertionError("actionability click must not be used")

    async def evaluate(self, script: str) -> None:
        assert script == "(element) => element.click()"
        self._page.click_index(self._index)


class FakePaginationLocator:
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    async def evaluate_all(self, _script: str) -> list[dict[str, object]]:
        return self._page.pagination_items()

    def nth(self, index: int) -> FakeItemLocator:
        return FakeItemLocator(self._page, index)

    async def count(self) -> int:
        return 0


class FakePage:
    def __init__(self) -> None:
        self.url = "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis"
        self.pages = [1, 2]
        self.active = 1
        self.clicked: list[int] = []

    def locator(self, _selector: str) -> FakePaginationLocator:
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


def _payload(page: FakePage) -> dict[str, object]:
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


def _observation() -> dict[str, object]:
    return {
        "host": "affiliate.tiktokshopglobalselling.com",
        "method": "POST",
        "path": "/api/v1/oec/affiliate/compass/transaction/detail_list/get",
        "payloadDiscriminator": "tiktok_affiliate_video_detail_list.v1",
        "pagination": {"mode": "unknown"},
    }


async def _capture(
    pager: TikTokAffiliateAnalyticsPager,
    lock: asyncio.Lock,
    page: FakePage,
    context: AffiliateAnalyticsResponseContext,
) -> None:
    async with lock:
        await pager.handle_payload(
            page,  # type: ignore[arg-type]
            "videos",
            _payload(page),
            _observation(),
            context,
        )
    await pager.wait_for_pending()


def _pager(lock, persist, finalize) -> TikTokAffiliateAnalyticsPager:
    return TikTokAffiliateAnalyticsPager(
        lock,
        guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
        settle_delay_seconds=0,
        watchdog_interval_seconds=0,
        page_persister=persist,
        terminal_handler=finalize,
    )


def test_pager_is_passive_until_first_valid_response() -> None:
    async def run() -> tuple[list[int], dict[str, dict[str, str]]]:
        lock = asyncio.Lock()
        page = FakePage()
        pager = _pager(lock, None, None)
        await asyncio.sleep(0)
        return page.clicked, pager.request_templates

    assert asyncio.run(run()) == ([], {})


def test_pager_keeps_api_transport_outside_the_paging_state_machine() -> None:
    source = inspect.getsource(TikTokAffiliateAnalyticsPager)
    driver_source = inspect.getsource(AffiliatePagingDriver)

    assert "fetch(" not in source.casefold()
    assert "fetch(" not in driver_source.casefold()
    assert 'evaluate("(element) => element.click()")' in driver_source


def test_video_pages_persist_before_advance_and_finalize_complete() -> None:
    async def run():
        lock = asyncio.Lock()
        page = FakePage()
        persisted = []
        finalized = []

        async def persist(resource, payload, observation, context, current, next_page):
            assert context.platform_shop_id == "platform-shop-1"
            persisted.append((resource, current, next_page, page.clicked.copy()))

        async def finalize(resource, snapshot):
            finalized.append((resource, dict(snapshot)))

        pager = _pager(lock, persist, finalize)
        context = AffiliateAnalyticsResponseContext("platform-shop-1", "request-1")
        await _capture(pager, lock, page, context)
        await _capture(pager, lock, page, context)
        return page.clicked, persisted, finalized

    clicked, persisted, finalized = asyncio.run(run())

    assert clicked == [2]
    assert persisted == [
        ("videos", 1, 2, []),
        ("videos", 2, None, [2]),
    ]
    assert len(finalized) == 1
    assert finalized[0][1]["status"] == "complete"
    assert finalized[0][1]["records_unique"] == 2


def test_video_persistence_failure_stops_before_page_advance(capsys) -> None:
    async def run():
        lock = asyncio.Lock()
        page = FakePage()
        finalized = []

        async def fail_persist(*_args):
            raise RuntimeError("database unavailable")

        async def finalize(resource, snapshot):
            finalized.append((resource, dict(snapshot)))

        pager = _pager(lock, fail_persist, finalize)
        await _capture(
            pager,
            lock,
            page,
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
        )
        return page.clicked, pager.resource_states, finalized

    clicked, states, finalized = asyncio.run(run())

    assert clicked == []
    assert states["videos"]["status"] == "partial"
    assert states["videos"]["failure_category"] == "page_failed"
    assert finalized[0][1]["status"] == "partial"
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    failure = next(
        event
        for event in events
        if event["event"] == "affiliate_analytics_page_persist_failed_runtime_error"
    )
    assert "database unavailable" not in failure.values()
