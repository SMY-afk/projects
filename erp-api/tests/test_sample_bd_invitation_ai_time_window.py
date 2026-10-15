from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.sample_bd_invitation_ai_times import (
    AiInvitationTimes,
    parse_invitation_time,
)

SUBMITTED = datetime(2026, 9, 27, 3, 32, tzinfo=UTC)


@pytest.mark.parametrize(
    ("invited", "expected"),
    [
        (SUBMITTED - timedelta(days=7) + timedelta(seconds=1), "hit"),
        (SUBMITTED - timedelta(days=7), "miss"),
        (SUBMITTED - timedelta(days=7, seconds=1), "miss"),
        (SUBMITTED, "hit"),
        (SUBMITTED + timedelta(seconds=1), "miss"),
    ],
)
def test_ai_hit_is_half_open_window_at_bd_submission(invited, expected):
    source = AiInvitationTimes.from_rows(
        [("@erika.withak", invited)], now=SUBMITTED + timedelta(hours=1)
    )
    assert source.classify("erika.withak", SUBMITTED) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/09/20 11:32", datetime(2026, 9, 20, 3, 32, tzinfo=UTC)),
        ("2026-09-20", datetime(2026, 9, 19, 16, tzinfo=UTC)),
        ("2026-09-20T11:32:00+08:00", datetime(2026, 9, 20, 3, 32, tzinfo=UTC)),
        (datetime(2026, 9, 20, 11, 32), datetime(2026, 9, 20, 3, 32, tzinfo=UTC)),  # noqa: DTZ001
        (None, None),
        ("", None),
        ("bad date", None),
        (True, None),
        (45000, None),
    ],
)
def test_invitation_time_contract_uses_shanghai_not_refresh_clock(raw, expected):
    assert parse_invitation_time(raw) == expected


def test_date_only_reaches_boundary_at_shanghai_midnight():
    source = AiInvitationTimes.from_rows(
        [("erika.withak", "2026/09/20")], now=SUBMITTED
    )
    boundary = datetime(2026, 9, 26, 16, tzinfo=UTC)
    assert source.classify("erika.withak", boundary - timedelta(seconds=1)) == "hit"
    assert source.classify("erika.withak", boundary) == "miss"


@pytest.mark.parametrize("raw", [None, "bad date", "2026/09/28 11:32"])
def test_present_account_with_unverified_time_never_grants_protection(raw):
    source = AiInvitationTimes.from_rows([("erika.withak", raw)], now=SUBMITTED)
    assert source.classify("erika.withak", SUBMITTED) == "pending"
    assert "erika.withak" in source.creator_ids
    assert source.classify("not-in-complete-source", SUBMITTED) == "miss"


def test_duplicates_select_latest_eligible_invitation_not_first_row():
    source = AiInvitationTimes.from_rows(
        [
            ("erika.withak", "2026/09/01 11:32"),
            ("@erika.withak", "2026/09/26 11:32"),
            ("erika.withak", "2026/09/27 11:40"),
        ],
        now=SUBMITTED + timedelta(hours=1),
    )
    assert source.classify("erika.withak", SUBMITTED) == "hit"


def test_duplicate_invalid_time_does_not_silently_disappear():
    source = AiInvitationTimes.from_rows(
        [("erika.withak", "2026/09/26"), ("erika.withak", "bad date")], now=SUBMITTED
    )
    assert source.classify("erika.withak", SUBMITTED) == "pending"
