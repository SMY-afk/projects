import os

from scripts.run_ziniao_affiliate_watch import (
    DEFAULT_CAPTURE_SESSION_BATCH_SIZE,
    _configure_capture_session_defaults,
    _next_retry_delay,
)


def test_ziniao_listener_stops_after_three_backoff_retries() -> None:
    delays = (30.0, 60.0, 300.0)

    assert [_next_retry_delay(index, delays) for index in range(4)] == [
        30.0,
        60.0,
        300.0,
        None,
    ]


def test_ziniao_listener_reuses_one_cdp_session_for_a_task_batch(
    monkeypatch,
) -> None:
    monkeypatch.delenv("AFFILIATE_CAPTURE_SESSION_BATCH_SIZE", raising=False)

    _configure_capture_session_defaults()

    assert os.environ["AFFILIATE_CAPTURE_SESSION_BATCH_SIZE"] == str(
        DEFAULT_CAPTURE_SESSION_BATCH_SIZE
    )


def test_ziniao_listener_allows_only_one_affiliate_task_per_sample_round() -> None:
    assert DEFAULT_CAPTURE_SESSION_BATCH_SIZE == 1
