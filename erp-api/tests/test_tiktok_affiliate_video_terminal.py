import asyncio

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import (
    CaptureGuardConfig,
)


class _CaptchaLocator:
    async def count(self) -> int:
        return 0


class _Page:
    url = "https://affiliate-us.tiktok.com/insights/video-analysis"

    def locator(self, _selector: str) -> _CaptchaLocator:
        return _CaptchaLocator()


def _payload(ids: list[str], total: int) -> dict:
    return {
        "data": {
            "video_list_segments_v2": [
                {
                    "total": total,
                    "video_performances": [
                        {"video_info": {"item_id": item}} for item in ids
                    ],
                }
            ]
        }
    }


def test_direct_video_stops_at_short_expected_last_page_for_reconciliation() -> None:
    async def run() -> tuple[list[int], list[tuple[int, int | None]], dict]:
        lock = asyncio.Lock()
        current = 1
        requested: list[int] = []
        persisted: list[tuple[int, int | None]] = []

        async def request_page(number: int) -> None:
            nonlocal current
            current = number
            requested.append(number)

        async def persist(_resource, _payload, _observation, _context, page, next_page):
            persisted.append((page, next_page))

        pager = TikTokAffiliateAnalyticsPager(
            lock,
            guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
            settle_delay_seconds=0,
            watchdog_interval_seconds=0,
            page_requester=request_page,
            page_number_provider=lambda: current,
            page_persister=persist,
        )
        context = AffiliateAnalyticsResponseContext(
            "shop",
            "request",
            request_url="https://affiliate-us.tiktok.com/api/v1/oec/affiliate/compass/transaction/detail_list/get",
            request_body={
                "params": {
                    "video_list_params_v2": [
                        {
                            "page_param": {"page_no": 1, "page_size": 2},
                        }
                    ]
                }
            },
        )
        observation = {
            "host": "affiliate-us.tiktok.com",
            "method": "POST",
            "path": "/api/v1/oec/affiliate/compass/transaction/detail_list/get",
            "payloadDiscriminator": "tiktok_affiliate_video_detail_list.v1",
        }
        page = _Page()
        for number, ids in enumerate((["a", "b"], ["c"], ["d"]), 1):
            context.request_body["params"]["video_list_params_v2"][0]["page_param"][
                "page_no"
            ] = number
            async with lock:
                await pager.handle_payload(
                    page, "videos", _payload(ids, 5), observation, context
                )
            await pager.wait_for_pending()
        state = pager.resource_states["videos"]
        await pager.stop()
        return requested, persisted, state

    requested, persisted, state = asyncio.run(run())
    assert requested == [2, 3]
    assert persisted == [(1, 2), (2, 3), (3, None)]
    assert state["status"] == "partial"
    assert state["failure_category"] == "total_count_mismatch"
