import asyncio

from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
    _PageState,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import CaptureGuardConfig


class _HiddenLocator:
    async def count(self) -> int:
        return 0


class _Page:
    url = "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"

    def locator(self, _selector: str) -> _HiddenLocator:
        return _HiddenLocator()


def _payload(creator_id: str, *, has_more: bool) -> dict[str, object]:
    return {
        "data": {
            "segments": [
                {
                    "list_control": {
                        "next_pagination": {"has_more": has_more, "total": 2}
                    },
                    "timed_lists": [{"stats": [{"id": creator_id}]}],
                }
            ]
        }
    }


def test_watchdog_does_not_finalize_while_terminal_page_is_persisting() -> None:
    async def run() -> int:
        finalized = 0

        async def terminal_handler(_resource, _snapshot) -> None:
            nonlocal finalized
            finalized += 1

        pager = TikTokAffiliateAnalyticsPager(
            asyncio.Lock(),
            guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
            watchdog_interval_seconds=0.01,
            terminal_handler=terminal_handler,
        )
        pager._guard.record_page("creators", 1, _payload("one", has_more=True))
        state = _PageState(_Page(), "creators", ".kora-pagination-item")  # type: ignore[arg-type]
        watcher = asyncio.create_task(pager._watch_resource(state))
        await asyncio.sleep(0)
        pager._guard.record_page("creators", 2, _payload("two", has_more=False))
        await watcher
        return finalized

    assert asyncio.run(run()) == 0
