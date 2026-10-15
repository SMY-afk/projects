from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.sample_cooperation_records import (
    business_note,
    decision_payload,
    processing_result,
)
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_ALLOWED_EVENT,
    COOPERATION_BD_INVITATION_EVENT,
    COOPERATION_EXCEPTION_EVENT,
    COOPERATION_OWNER_PROTECTED_EVENT,
    COOPERATION_RECENT_EVENT,
    BdInvitationProtection,
    CooperationCandidate,
    CooperationRecipient,
    CooperationRow,
    CooperationSnapshot,
    CreatorAssignmentOwner,
    decide_cooperation,
)


def _candidate(creator_id: str | None = "Creator-One") -> CooperationCandidate:
    return CooperationCandidate(
        application_id=uuid4(),
        platform_application_id="application-1",
        creator_id=creator_id,
        shop_name="Akeleo Toys",
    )


def _row(
    approved_date: object,
    *,
    owner: str = "Alice",
    source: str = "童车",
) -> CooperationRow:
    return CooperationRow(
        source=source,
        record_id=str(uuid4()),
        account_name=" @creator-one\u200b ",
        bd_owner=owner,
        approved_date=approved_date,
    )


def _snapshot(
    *rows: CooperationRow,
    valid_creator_ids: frozenset[str] = frozenset(),
    ai_invitation_creator_ids: frozenset[str] = frozenset(),
    assignment_owners: dict[str, CreatorAssignmentOwner] | None = None,
    protected_creators: dict[str, BdInvitationProtection] | None = None,
) -> CooperationSnapshot:
    return CooperationSnapshot(
        rows=rows,
        recipients={
            "alice": CooperationRecipient("Alice", "ou-alice"),
            "bob": CooperationRecipient("Bob", "ou-bob"),
        },
        current_bd_names=frozenset({"alice", "bob"}),
        valid_creator_ids=valid_creator_ids,
        ai_invitation_creator_ids=ai_invitation_creator_ids,
        assignment_owners=assignment_owners or {},
        protected_creators=protected_creators or {},
    )


def _owner(*, days_ago: int, bd_name: str = "Alice") -> CreatorAssignmentOwner:
    return CreatorAssignmentOwner(
        creator_id="creator-one",
        bd_name=bd_name,
        assigned_at=datetime(2026, 9, 23, 8, tzinfo=UTC)
        - timedelta(days=days_ago),
        application_id=uuid4(),
        shop_name="Akeleo Fun Toys",
    )


def test_recent_cross_shop_assignment_blocks_and_notifies_earliest_owner() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(assignment_owners={"creator-one": _owner(days_ago=3)}),
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_OWNER_PROTECTED_EVENT
    assert decision.reason == "creator_assignment_within_7_days"
    assert decision.recipients == (CooperationRecipient("Alice", "ou-alice"),)
    assert decision.owner_bd_name == "Alice"


def test_old_assignment_allows_when_creator_is_absent_from_both_lists() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(assignment_owners={"creator-one": _owner(days_ago=8)}),
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"


@pytest.mark.parametrize("source", ["valid", "ai"])
def test_old_assignment_remains_with_original_bd_when_creator_is_listed(source) -> None:
    listed = frozenset({"creator-one"})
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            valid_creator_ids=listed if source == "valid" else frozenset(),
            ai_invitation_creator_ids=listed if source == "ai" else frozenset(),
            assignment_owners={"creator-one": _owner(days_ago=8)},
        ),
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_OWNER_PROTECTED_EVENT
    assert decision.reason == f"creator_assignment_over_7_days_in_{source}_table"
    assert decision.recipients == (CooperationRecipient("Alice", "ou-alice"),)


def test_assignment_owner_outside_current_roster_allows_assignment() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            assignment_owners={
                "creator-one": _owner(days_ago=1, bd_name="Unknown BD")
            }
        ),
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"


def test_no_registration_allows_normal_assignment() -> None:
    decision = decide_cooperation(_candidate(), _snapshot(), today=date(2026, 9, 16))

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"


def test_bd_invitation_protection_blocks_assignment_before_other_rules() -> None:
    expires_at = datetime(2026, 9, 28, 6, tzinfo=UTC)
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026.09.22"),
            protected_creators={
                "creator-one": BdInvitationProtection(
                    "rec-protection", "creator-one", "Alice", expires_at
                )
            },
        ),
        today=date(2026, 9, 22),
    )

    assert decision.event_type == COOPERATION_BD_INVITATION_EVENT
    assert decision.reason == "bd_invitation_protected"
    assert decision.protected_bd_name == "Alice"
    assert decision.protected_until == expires_at
    assert decision.blocks_assignment is True
    assert processing_result(decision.event_type) == "BD自主邀约保护中，不进入分配记录"
    assert "保护BD：Alice" in business_note(decision)
    assert decision_payload(decision)["protected_until"] == expires_at.isoformat()


def test_daily_valid_creator_without_cooperation_row_is_blocked() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(valid_creator_ids=frozenset({"creator-one"})),
        today=date(2026, 9, 21),
    )

    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "active_creator_bd_unavailable"
    assert decision.recipients == ()


def test_old_registrations_allow_assignment_when_creator_is_not_valid() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(_row("2026.09.13"), _row("8.20", owner="Bob")),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "registered_before_recent_window"
    assert decision.matched_count == 2


def test_old_registration_blocks_when_creator_is_in_daily_valid_table() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026.09.13"),
            _row("8.20", owner="Bob"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_ACTIVE_CREATOR_EVENT
    assert decision.reason == "active_creator_after_recent_window"
    assert decision.recent_date == date(2026, 9, 13)
    assert decision.recipients == (
        CooperationRecipient("Alice", "ou-alice"),
        CooperationRecipient("Bob", "ou-bob"),
    )


def test_old_valid_creator_with_nonmember_bd_can_be_assigned() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026.09.13", owner="Unknown BD"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "no_current_bd_owner"


def test_nonmember_bd_is_excluded_when_one_current_owner_remains() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026.06.04", owner="Alice"),
            _row("2026.07.17", owner="Former BD"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 10, 9),
    )

    assert decision.event_type == COOPERATION_ACTIVE_CREATOR_EVENT
    assert decision.reason == "active_creator_after_recent_window"
    assert decision.recipients == (CooperationRecipient("Alice", "ou-alice"),)


def test_valid_creator_with_only_nonmember_bd_can_be_assigned() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026.07.17", owner="Unknown BD"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 10, 9),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "no_current_bd_owner"


def test_recent_assignment_owner_outside_current_roster_does_not_block() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            assignment_owners={
                "creator-one": _owner(days_ago=3, bd_name="Former BD")
            }
        ),
        today=date(2026, 9, 23),
        now=datetime(2026, 9, 23, 8, tzinfo=UTC),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"


def test_any_recent_registration_blocks_assignment_and_notifies_all_recent_bds() -> (
    None
):
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row("2026-08-20"),
            _row("9.14", owner="Alice"),
            _row("2026/09/16", owner="Bob", source="遥控车"),
        ),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_RECENT_EVENT
    assert decision.reason == "recent_registration"
    assert decision.recent_date == date(2026, 9, 16)
    assert decision.recipients == (
        CooperationRecipient("Alice", "ou-alice"),
        CooperationRecipient("Bob", "ou-bob"),
    )


def test_two_digit_year_is_parsed_as_2000s() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(_row("26/9/16")),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_RECENT_EVENT
    assert decision.reason == "recent_registration"
    assert decision.recent_date == date(2026, 9, 16)


def test_today_and_previous_two_days_are_recent_but_day_three_is_old() -> None:
    for value in ("2026-09-14", "2026-09-15", "2026-09-16"):
        decision = decide_cooperation(
            _candidate(), _snapshot(_row(value)), today=date(2026, 9, 16)
        )
        assert decision.event_type == COOPERATION_RECENT_EVENT

    old = decide_cooperation(
        _candidate(), _snapshot(_row("2026-09-13")), today=date(2026, 9, 16)
    )
    assert old.event_type == COOPERATION_ALLOWED_EVENT


def test_blank_dates_mean_no_completed_collaboration() -> None:
    for value in (None, "", "   "):
        decision = decide_cooperation(
            _candidate(), _snapshot(_row(value)), today=date(2026, 9, 16)
        )
        assert decision.event_type == COOPERATION_ALLOWED_EVENT
        assert decision.reason == "no_completed_collaboration"


def test_blank_date_valid_creator_blocks_and_routes_to_original_bd() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row(None, owner="Alice", source="遥控车"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 9, 21),
    )

    assert decision.event_type == COOPERATION_ACTIVE_CREATOR_EVENT
    assert decision.reason == "active_creator_without_approved_date"
    assert decision.recent_date is None
    assert decision.recipients == (CooperationRecipient("Alice", "ou-alice"),)


def test_blank_date_valid_creator_with_nonmember_bd_can_be_assigned() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(
            _row(None, owner="Unknown BD"),
            valid_creator_ids=frozenset({"creator-one"}),
        ),
        today=date(2026, 9, 21),
    )

    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "no_current_bd_owner"


def test_blank_date_is_ignored_when_another_registration_has_a_date() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(_row(""), _row("2026-09-15", owner="Bob")),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_RECENT_EVENT
    assert decision.recipients == (CooperationRecipient("Bob", "ou-bob"),)


def test_nonblank_unparseable_date_is_a_precheck_exception() -> None:
    decision = decide_cooperation(
        _candidate(), _snapshot(_row("not-a-date")), today=date(2026, 9, 16)
    )

    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "sample_approved_date_invalid"


def test_recent_registration_with_missing_bd_stays_blocked() -> None:
    decision = decide_cooperation(
        _candidate(),
        _snapshot(_row("2026-09-15", owner="")),
        today=date(2026, 9, 16),
    )

    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "bd_owner_missing"
    assert decision.recipients == ()


def test_unique_bd_short_name_resolves_to_roster_recipient() -> None:
    snapshot = CooperationSnapshot(
        rows=(_row("26/9/16", owner="曼唯"),),
        recipients={
            "example-f667fc1c0974": CooperationRecipient("example-f667fc1c0974", "ou-cai-manwei"),
        },
    )

    decision = decide_cooperation(_candidate(), snapshot, today=date(2026, 9, 16))

    assert decision.event_type == COOPERATION_RECENT_EVENT
    assert decision.recipients == (CooperationRecipient("example-f667fc1c0974", "ou-cai-manwei"),)


def test_ambiguous_bd_short_name_remains_unresolved() -> None:
    snapshot = CooperationSnapshot(
        rows=(_row("26/9/16", owner="曼唯"),),
        recipients={
            "example-f667fc1c0974": CooperationRecipient("example-f667fc1c0974", "ou-cai-manwei"),
            "王曼唯": CooperationRecipient("王曼唯", "ou-wang-manwei"),
        },
    )

    decision = decide_cooperation(_candidate(), snapshot, today=date(2026, 9, 16))

    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "bd_recipient_unresolved"


def test_missing_creator_id_is_an_exception_without_name_fallback() -> None:
    decision = decide_cooperation(
        _candidate(None), _snapshot(), today=date(2026, 9, 16)
    )

    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "creator_id_missing"
