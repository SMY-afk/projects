from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

CREATOR_PROFILE_MAX_AGE = timedelta(minutes=5)
FUTURE_CLOCK_SKEW = timedelta(minutes=1)
CreatorProfileStatus = Literal["current", "incomplete", "stale"]


def creator_profile_status(
    snapshot: object,
    observed_at: datetime | None,
    *,
    now: datetime,
) -> CreatorProfileStatus:
    if now.tzinfo is None:
        raise ValueError("Creator profile freshness time must include a timezone.")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("creator_details_complete") is not True
    ):
        return "incomplete"
    if observed_at is None or observed_at.tzinfo is None:
        return "stale"
    age = now.astimezone(UTC) - observed_at.astimezone(UTC)
    if age < -FUTURE_CLOCK_SKEW or age > CREATOR_PROFILE_MAX_AGE:
        return "stale"
    return "current"


def creator_profile_refresh_due(
    snapshot: object,
    observed_at: datetime | None,
    *,
    now: datetime,
) -> bool:
    return creator_profile_status(snapshot, observed_at, now=now) != "current"
