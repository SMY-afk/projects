import asyncio
from types import SimpleNamespace

from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import (
    CaptureGuardConfig,
)


class SafePage:
    url = "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"

    def locator(self, selector):
        return SimpleNamespace(count=_zero)


async def _zero() -> int:
    return 0


def _running_creator_payload() -> dict[str, object]:
    return {
        "data": {
            "segments": [
                {
                    "list_control": {"next_pagination": {"has_more": True, "total": 2}},
                    "timed_lists": [{"stats": [{"id": "creator-1"}]}],
                }
            ]
        }
    }


def test_runtime_watchdog_persists_partial_terminal_state() -> None:
    async def run() -> list[tuple[str, dict[str, object]]]:
        terminal_events = []

        async def finalize(resource, snapshot):
            terminal_events.append((resource, snapshot))

        pager = TikTokAffiliateAnalyticsPager(
            asyncio.Lock(),
            guard_config=CaptureGuardConfig(
                max_run_seconds=0.001,
                min_request_interval_seconds=0,
            ),
            watchdog_interval_seconds=0.001,
            terminal_handler=finalize,
        )
        pager._guard.record_page("creators", 1, _running_creator_payload())
        await pager._watch_resource(
            SimpleNamespace(resource="creators", page=SafePage())
        )
        return terminal_events

    events = asyncio.run(run())

    assert events[0][0] == "creators"
    assert events[0][1]["status"] == "partial"
    assert events[0][1]["failure_category"] == "max_runtime_exceeded"
