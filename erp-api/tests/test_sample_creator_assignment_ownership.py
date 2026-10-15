from datetime import UTC, datetime, timedelta
from uuid import uuid4

from erp_api.services.sample_creator_assignment_ownership import (
    CreatorAssignmentHistory,
    select_current_assignment_owner,
)

NOW = datetime(2026, 9, 23, 8, tzinfo=UTC)


def _history(days_ago: int, bd_name: str) -> CreatorAssignmentHistory:
    return CreatorAssignmentHistory(
        creator_id="creator-one",
        bd_name=bd_name,
        assigned_at=NOW - timedelta(days=days_ago),
        application_id=uuid4(),
        shop_name="shop",
    )


def test_earliest_assignment_in_current_seven_day_window_is_owner() -> None:
    first = _history(3, "Alice")
    later = _history(2, "Bob")

    owner = select_current_assignment_owner((later, first))

    assert owner.bd_name == "Alice"
    assert owner.assigned_at == first.assigned_at


def test_assignment_after_previous_window_starts_a_new_owner_window() -> None:
    old = _history(20, "Alice")
    conflict_in_old_window = _history(16, "Bob")
    new = _history(5, "Carol")
    conflict_in_new_window = _history(2, "David")

    owner = select_current_assignment_owner(
        (conflict_in_new_window, old, new, conflict_in_old_window)
    )

    assert owner.bd_name == "Carol"
    assert owner.assigned_at == new.assigned_at


def test_exactly_seven_days_is_still_the_same_owner_window() -> None:
    first = _history(14, "Alice")
    exactly_seven_days_later = CreatorAssignmentHistory(
        creator_id="creator-one",
        bd_name="Bob",
        assigned_at=first.assigned_at + timedelta(days=7),
        application_id=uuid4(),
        shop_name="other-shop",
    )

    owner = select_current_assignment_owner((first, exactly_seven_days_later))

    assert owner.bd_name == "Alice"
