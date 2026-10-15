from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from backend.app.services.capture_logging import capture_log
from backend.app.services.hubstudio_raw_sample_capture import (
    SampleRawCaptureBatch,
    capture_review_batch,
)
from backend.app.services.local_browser_security import browser_security_state
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_batch_validation import validate_stored_raw_pages
from backend.app.services.sample_watch_error_category import (
    is_retryable_raw_capture_error,
    requires_cdp_rediscovery,
)


def recover_fresh_completed(store, *, now=None):
    """Preserve old RAW history, but recapture a window older than fifteen minutes."""
    batch = store.recover_completed()
    if batch is None:
        return None
    now = now or datetime.now(UTC)
    pages = store.load_pages(batch)
    ages = [(now - page.response_observed_at).total_seconds() for page in pages]
    if not ages or min(ages) < -5:
        raise RuntimeError("sample_capture_clock_invalid")
    if max(ages) > 900:
        store.supersede_completed(batch, reason="capture_expired")
        return None
    try:
        validate_stored_raw_pages(
            pages, expected_total=batch.expected_total,
            captured_total=batch.captured_total, terminal_confirmed=True,
        )
    except RuntimeError:
        store.supersede_completed(batch, reason="invalid_pagination")
        return None
    return batch


async def capture_review_batch_with_retry(
    cdp_url: str,
    platform_shop_id: str,
    store: SampleRawBatchStore,
    *,
    timeout_seconds: float,
    retry_delay_seconds: float = 30,
    max_attempts: int = 2,
) -> SampleRawCaptureBatch:
    """Replay the complete batch after a transient gap or CDP interruption."""
    if max_attempts < 1:
        raise ValueError("RAW capture attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return await capture_review_batch(
                cdp_url,
                platform_shop_id,
                store,
                timeout_seconds=timeout_seconds,
            )
        except Exception as error:
            if not is_retryable_raw_capture_error(error):
                raise
            reason = (
                "cdp_disconnect_retry"
                if requires_cdp_rediscovery(error)
                else "incomplete_batch_retry"
            )
            abandoned = await asyncio.to_thread(store.abandon_capturing, reason)
            capture_log(
                "hubstudio_raw_sample_capture_retry",
                attempt=attempt + 1,
                reason=reason,
                abandoned_batches=abandoned,
            )
            if attempt + 1 >= max_attempts:
                raise
            await asyncio.sleep(retry_delay_seconds * (attempt + 1))
            state = await asyncio.wait_for(browser_security_state(cdp_url), 15)
            if state != "online":
                raise RuntimeError(state) from error
    raise AssertionError("unreachable")
