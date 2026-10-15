from backend.app.services.tiktok_affiliate_analytics_run_state import (
    AffiliateAnalyticsRunGuard,
    CaptureGuardConfig,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_default_request_interval_is_conservative() -> None:
    assert CaptureGuardConfig().min_request_interval_seconds == 3


def _creator_payload(
    ids: list[str],
    *,
    total: int,
    has_more: bool,
    next_cursor: str | None = None,
) -> dict[str, object]:
    pagination: dict[str, object] = {
        "has_more": has_more,
        "next_page": 2,
        "total": total,
        "total_page": 2,
    }
    if next_cursor is not None:
        pagination["next_cursor"] = next_cursor
    return {
        "data": {
            "segments": [
                {
                    "list_control": {"next_pagination": pagination},
                    "timed_lists": [
                        {"stats": [{"id": creator_id} for creator_id in ids]}
                    ],
                }
            ]
        }
    }


def _video_payload(ids: list[str], *, total: int) -> dict[str, object]:
    return {
        "data": {
            "video_list_segments_v2": [
                {
                    "total": total,
                    "video_performances": [
                        {"video_info": {"item_id": video_id}} for video_id in ids
                    ],
                }
            ]
        }
    }


def test_max_pages_stops_only_the_affected_resource() -> None:
    guard = AffiliateAnalyticsRunGuard(CaptureGuardConfig(max_pages=2))

    guard.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=3, has_more=True),
    )
    decision = guard.record_page(
        "creators",
        2,
        _creator_payload(["creator-2"], total=3, has_more=True),
    )

    assert decision.stop is True
    assert guard.snapshot("creators")["status"] == "partial"
    assert guard.snapshot("creators")["failure_category"] == "max_pages_exceeded"
    assert guard.snapshot("videos")["status"] == "idle"


def test_max_runtime_and_minimum_request_interval_use_monotonic_clock() -> None:
    clock = FakeClock()
    guard = AffiliateAnalyticsRunGuard(
        CaptureGuardConfig(
            max_run_seconds=5,
            min_request_interval_seconds=2,
        ),
        clock=clock,
    )
    guard.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=2, has_more=True),
    )
    guard.mark_request("creators")
    clock.value = 0.5

    assert guard.remaining_request_delay("creators") == 1.5

    clock.value = 5.1
    assert guard.enforce_runtime_limit("creators") is True
    assert guard.snapshot("creators")["failure_category"] == "max_runtime_exceeded"


def test_repeated_cursor_hash_stops_without_exposing_cursor() -> None:
    guard = AffiliateAnalyticsRunGuard()
    payload = _creator_payload(
        ["creator-1"],
        total=3,
        has_more=True,
        next_cursor="private-cursor",
    )

    guard.record_page("creators", 1, payload)
    decision = guard.record_page("creators", 2, payload)
    snapshot = guard.snapshot("creators")

    assert decision.stop is True
    assert snapshot["failure_category"] == "cursor_interrupted"
    assert snapshot["last_cursor_hash"].startswith("sha256:")
    assert "private-cursor" not in str(snapshot)


def test_consecutive_empty_pages_stop_as_partial() -> None:
    guard = AffiliateAnalyticsRunGuard(
        CaptureGuardConfig(max_consecutive_empty_pages=2)
    )

    guard.record_page("videos", 1, _video_payload([], total=10))
    decision = guard.record_page("videos", 2, _video_payload([], total=10))

    assert decision.stop is True
    snapshot = guard.snapshot("videos")
    assert snapshot["status"] == "partial"
    assert snapshot["failure_category"] == "consecutive_empty_pages"


def test_complete_requires_first_page_and_matching_unique_total() -> None:
    complete = AffiliateAnalyticsRunGuard()
    complete.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=2, has_more=True),
    )
    complete.record_page(
        "creators",
        2,
        _creator_payload(["creator-2"], total=2, has_more=False),
    )

    partial = AffiliateAnalyticsRunGuard()
    partial.record_page(
        "creators",
        2,
        _creator_payload(["creator-2"], total=2, has_more=False),
    )

    assert complete.snapshot("creators")["status"] == "complete"
    assert partial.snapshot("creators")["status"] == "partial"
    assert partial.snapshot("creators")["failure_category"] == (
        "started_after_first_page"
    )


def test_missing_cursor_while_has_more_is_partial() -> None:
    guard = AffiliateAnalyticsRunGuard()

    decision = guard.record_page(
        "creators",
        1,
        _creator_payload(
            ["creator-1"],
            total=2,
            has_more=True,
            next_cursor="",
        ),
    )

    assert decision.stop is True
    assert guard.snapshot("creators")["status"] == "partial"
    assert guard.snapshot("creators")["failure_category"] == "cursor_interrupted"


def test_terminal_total_mismatch_is_partial() -> None:
    guard = AffiliateAnalyticsRunGuard()

    guard.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=2, has_more=False),
    )

    assert guard.snapshot("creators")["status"] == "partial"
    assert guard.snapshot("creators")["failure_category"] == "total_count_mismatch"


def test_missing_next_page_control_completes_only_when_unique_total_matches() -> None:
    complete = AffiliateAnalyticsRunGuard()
    complete.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=1, has_more=True),
    )
    complete.finish_ui_terminal("creators")

    partial = AffiliateAnalyticsRunGuard()
    partial.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=2, has_more=True),
    )
    partial.finish_ui_terminal("creators")

    assert complete.snapshot("creators")["status"] == "complete"
    assert complete.snapshot("creators")["terminal_reason"] == ("no_next_page_control")
    assert partial.snapshot("creators")["status"] == "partial"
    assert partial.snapshot("creators")["failure_category"] == ("total_count_mismatch")


def test_failure_after_a_persisted_page_is_partial() -> None:
    guard = AffiliateAnalyticsRunGuard()
    guard.record_page(
        "creators",
        1,
        _creator_payload(["creator-1"], total=2, has_more=True),
    )

    guard.fail("creators", status="failed", category="rate_limited")

    assert guard.snapshot("creators")["status"] == "partial"
    assert guard.snapshot("creators")["failure_category"] == "page_failed"


def test_duplicate_records_do_not_inflate_unique_completion_count() -> None:
    guard = AffiliateAnalyticsRunGuard()
    guard.record_page("videos", 1, _video_payload(["video-1", "video-1"], total=1))
    guard.finish_ui_terminal("videos")

    snapshot = guard.snapshot("videos")
    assert snapshot["records_received"] == 2
    assert snapshot["records_unique"] == 1
    assert snapshot["duplicates"] == 1
    assert snapshot["status"] == "complete"
    assert snapshot["failure_category"] is None


def test_video_stops_when_unique_records_reach_the_reported_total() -> None:
    guard = AffiliateAnalyticsRunGuard()

    decision = guard.record_page(
        "videos",
        1,
        _video_payload(["video-1", "video-2"], total=2),
    )

    snapshot = guard.snapshot("videos")
    assert decision.stop is True
    assert snapshot["status"] == "complete"
    assert snapshot["terminal_reason"] == "expected_total_reached"


def test_security_and_transport_failures_are_terminal_and_independent() -> None:
    guard = AffiliateAnalyticsRunGuard()

    guard.fail("creators", status="session_required", category="captcha")
    guard.fail("videos", status="failed", category="rate_limited")

    assert guard.snapshot("creators")["status"] == "session_required"
    assert guard.snapshot("creators")["failure_category"] == "captcha"
    assert guard.snapshot("videos")["status"] == "failed"
    assert guard.snapshot("videos")["failure_category"] == "rate_limited"
