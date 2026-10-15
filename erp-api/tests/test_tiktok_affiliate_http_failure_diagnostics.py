import asyncio
from types import SimpleNamespace

from backend.app.services import tiktok_affiliate_analytics_capture as capture


def test_http_rejection_logs_a_fixed_safe_reason(monkeypatch) -> None:
    events = []
    failures = []
    monkeypatch.setattr(
        capture,
        "_capture_log",
        lambda event, **_fields: events.append(event),
    )

    async def failure_handler(_page, resource, status, category):
        failures.append((resource, status, category))

    async def run() -> None:
        synchronizer = capture.TikTokAffiliateAnalyticsSynchronizer(
            asyncio.Lock(), failure_handler=failure_handler
        )
        response = SimpleNamespace(
            url="https://affiliate-us.tiktok.com" + capture.VIDEO_ANALYTICS_PATH,
            status=429,
            request=SimpleNamespace(
                method="POST", frame=SimpleNamespace(page=object())
            ),
        )
        await synchronizer.handle_response(response)

    asyncio.run(run())
    assert failures == [("videos", "failed", "rate_limited")]
    assert "affiliate_analytics_http_rate_limited" in events
