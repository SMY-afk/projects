from __future__ import annotations

from datetime import datetime, timedelta


def is_notification_due(event, now: datetime, processing_timeout: timedelta) -> bool:
    if event.status == "pending":
        return True
    if event.status == "retry_wait":
        return event.next_attempt_at is not None and event.next_attempt_at <= now
    if event.status == "processing":
        return event.updated_at <= now - processing_timeout
    return False
