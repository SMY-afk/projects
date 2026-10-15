from __future__ import annotations

import os


def capture_batch_size() -> int:
    raw = os.getenv("AFFILIATE_CAPTURE_SESSION_BATCH_SIZE", "1")
    try:
        value = int(raw)
    except ValueError:
        value = 1
    return min(20, max(1, value))


def capture_preflight_timeout_seconds() -> float:
    raw = os.getenv("AFFILIATE_CAPTURE_PREFLIGHT_TIMEOUT_SECONDS", "90")
    try:
        value = float(raw)
    except ValueError:
        value = 90.0
    return min(300.0, max(30.0, value))
