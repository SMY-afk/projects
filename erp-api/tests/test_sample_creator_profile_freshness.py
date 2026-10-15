from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.sample_creator_profile_freshness import (
    CREATOR_PROFILE_MAX_AGE,
    creator_profile_refresh_due,
    creator_profile_status,
)

NOW = datetime(2026, 9, 11, 3, tzinfo=UTC)
COMPLETE = {"schema_version": 2, "creator_details_complete": True}


def test_complete_profile_within_max_age_is_current() -> None:
    observed_at = NOW - CREATOR_PROFILE_MAX_AGE

    assert creator_profile_status(COMPLETE, observed_at, now=NOW) == "current"
    assert creator_profile_refresh_due(COMPLETE, observed_at, now=NOW) is False


def test_incomplete_or_old_profile_requires_refresh() -> None:
    assert creator_profile_status({}, NOW, now=NOW) == "incomplete"
    assert (
        creator_profile_status(
            COMPLETE,
            NOW - CREATOR_PROFILE_MAX_AGE - timedelta(seconds=1),
            now=NOW,
        )
        == "stale"
    )


def test_naive_freshness_clock_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        creator_profile_status(
            COMPLETE,
            NOW,
            now=datetime(2026, 9, 11, 3),  # noqa: DTZ001 - intentional invalid input
        )
