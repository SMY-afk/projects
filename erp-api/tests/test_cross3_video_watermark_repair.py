"""Provenance gates cannot be replaced by a complete-looking watermark."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts.repair_cross3_video_watermark_20261013 import (
    CAPTURE_ID,
    FILE_HASH,
    LATEST_DAY,
    RUN_ID,
    SHOPS,
    TENANT_ID,
    validate_receipt,
)


def receipt():
    return SimpleNamespace(
        id=RUN_ID, shop_id=SHOPS["cross-border-3"], tenant_id=TENANT_ID,
        job_id=f"remote-export:{CAPTURE_ID}:capture", resource_type="affiliate_video",
        account_type="AFFILIATE_ACCOUNTS", currency="USD", status="succeeded",
        fetched_count=1502, persisted_count=1502, latest_available_date=None,
        window_start=datetime(2026, 10, 8, 7, tzinfo=UTC),
        window_end=datetime(2026, 10, 10, 7, tzinfo=UTC),
    )


def test_exact_complete_original_and_direct_date_pass():
    now = datetime.now(UTC)
    validate_receipt(receipt(), [FILE_HASH], (LATEST_DAY, now), now)


@pytest.mark.parametrize("kind", ["count", "hash", "stale", "watermark"])
def test_missing_provenance_or_nonempty_other_watermark_block(kind):
    run = receipt()
    now = datetime.now(UTC)
    hashes = [FILE_HASH]
    observed = (LATEST_DAY, now)
    if kind == "count":
        run.persisted_count = 1501
    elif kind == "hash":
        hashes = ["not-the-original"]
    elif kind == "stale":
        observed = (LATEST_DAY, now - timedelta(hours=7))
    else:
        run.latest_available_date = LATEST_DAY - timedelta(days=1)
    with pytest.raises(ValueError):
        validate_receipt(run, hashes, observed, now)
