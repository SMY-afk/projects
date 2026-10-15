from collections import Counter
from datetime import UTC, datetime

import pytest

from erp_api.services.sample_assignment_workload_delta import (
    apply_assignment_to_workloads,
)
from erp_api.services.sample_bd_assignment import (
    AssignmentDecision,
    BdWorkload,
    classify_creator_level,
    select_bd_for_level,
    validate_bd_roster,
)


@pytest.mark.parametrize(
    ("gmv_minor", "expected"),
    [
        (0, "L0"),
        (99_999, "L0"),
        (100_000, "L1"),
        (500_000, "L2"),
        (2_500_000, "L3"),
        (6_000_000, "L4"),
        (15_000_000, "L5"),
        (40_000_000, "L6"),
        (150_000_000, "L7"),
    ],
)
def test_classify_creator_level_boundaries(gmv_minor: int, expected: str) -> None:
    assert classify_creator_level(gmv_minor) == expected


def test_classify_creator_level_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="negative"):
        classify_creator_level(-1)


def test_selection_never_repeats_most_recent_bd_for_same_level() -> None:
    decision = select_bd_for_level(
        "L7",
        [
            BdWorkload(
                name="BD A",
                total_assigned=8,
                last_received_levels=frozenset({"L7"}),
            ),
            BdWorkload(name="BD B", total_assigned=8),
        ],
    )

    assert decision.assigned_bd_name == "BD B"
    assert decision.excluded_reasons == {"bd a": "recent_level_recipient"}


def test_in_run_assignment_updates_record_based_workloads_immediately() -> None:
    roster = (
        BdWorkload(name="BD A", bd_id="bd-a"),
        BdWorkload(name="BD B", bd_id="bd-b"),
    )

    updated = apply_assignment_to_workloads(
        roster,
        AssignmentDecision("BD A", "L2", assigned_bd_id="bd-a"),
    )
    next_decision = select_bd_for_level("L2", updated)

    assert updated[0].level_counts == {"L2": 1}
    assert updated[0].total_assigned == 1
    assert updated[0].last_received_levels == frozenset({"L2"})
    assert next_decision.assigned_bd_name == "BD B"


def test_selection_balances_same_shop_level_before_total_workload() -> None:
    decision = select_bd_for_level(
        "L5",
        [
            BdWorkload(name="BD A", total_assigned=3, level_counts={"L5": 9}),
            BdWorkload(name="BD B", total_assigned=9, level_counts={"L5": 1}),
        ],
    )

    assert decision.assigned_bd_name == "BD B"


def test_selection_uses_total_then_oldest_assignment_as_tiebreakers() -> None:
    decision = select_bd_for_level(
        "L3",
        [
            BdWorkload(
                name="BD A",
                total_assigned=4,
                level_counts={"L3": 1},
                last_assigned_at=datetime(2026, 9, 2, tzinfo=UTC),
            ),
            BdWorkload(
                name="BD B",
                total_assigned=4,
                level_counts={"L3": 1},
                last_assigned_at=datetime(2026, 9, 1, tzinfo=UTC),
            ),
        ],
    )

    assert decision.assigned_bd_name == "BD B"


def test_selection_keeps_only_candidate_when_rotation_has_no_alternative() -> None:
    decision = select_bd_for_level(
        "L7",
        [
            BdWorkload(
                name="BD A",
                last_received_levels=frozenset({"L7"}),
            ),
        ],
    )

    assert decision.assigned_bd_name == "BD A"
    assert decision.decision_reason == "selected_level_balance_over_rotation"


def test_selection_preserves_level_balance_before_rotating_recipient() -> None:
    decision = select_bd_for_level(
        "L7",
        [
            BdWorkload(
                name="BD A",
                total_assigned=3,
                level_counts={"L7": 0},
                last_received_levels=frozenset({"L7"}),
            ),
            BdWorkload(name="BD B", total_assigned=4, level_counts={"L7": 1}),
        ],
    )

    assert decision.assigned_bd_name == "BD A"
    assert decision.decision_reason == "selected_level_balance_over_rotation"


def test_consecutive_assignments_fill_two_item_level_deficit_first() -> None:
    roster = (
        BdWorkload(
            name="BD A",
            bd_id="bd-a",
            total_assigned=7,
            level_counts={"L2": 2},
        ),
        BdWorkload(
            name="BD B",
            bd_id="bd-b",
            total_assigned=7,
            level_counts={"L2": 4},
        ),
        BdWorkload(
            name="BD C",
            bd_id="bd-c",
            total_assigned=6,
            level_counts={"L2": 4},
        ),
    )

    first = select_bd_for_level("L2", roster)
    after_first = apply_assignment_to_workloads(roster, first)
    second = select_bd_for_level("L2", after_first)
    after_second = apply_assignment_to_workloads(after_first, second)
    third = select_bd_for_level("L2", after_second)

    assert first.assigned_bd_name == "BD A"
    assert second.assigned_bd_name == "BD A"
    assert second.decision_reason == "selected_level_balance_over_rotation"
    assert third.assigned_bd_name != "BD A"
    assert third.decision_reason == "selected_level_rotation"


def test_level_counts_seven_eight_nine_must_assign_seven() -> None:
    decision = select_bd_for_level(
        "L2",
        [
            BdWorkload(name="BD 7", bd_id="bd-7", level_counts={"L2": 7}),
            BdWorkload(name="BD 8", bd_id="bd-8", level_counts={"L2": 8}),
            BdWorkload(name="BD 9", bd_id="bd-9", level_counts={"L2": 9}),
        ],
    )

    assert decision.assigned_bd_id == "bd-7"


def test_selection_filters_category_and_capacity_before_scoring() -> None:
    decision = select_bd_for_level(
        "L3",
        [
            BdWorkload(
                name="Wrong category",
                bd_id="wrong-category",
                categories=frozenset({"stroller"}),
            ),
            BdWorkload(
                name="At capacity",
                bd_id="full",
                categories=frozenset({"rc-car"}),
                current_pending=2,
                capacity=2,
            ),
            BdWorkload(
                name="Eligible",
                bd_id="eligible",
                categories=frozenset({"rc-car"}),
                current_pending=1,
                capacity=2,
            ),
        ],
        category="rc-car",
        assignment_key="sample-1",
    )

    assert decision.assigned_bd_id == "eligible"
    assert decision.excluded_reasons == {
        "wrong-category": "category_mismatch",
        "full": "at_capacity",
    }


def test_selection_blocks_instead_of_widening_level_gap_past_one() -> None:
    decision = select_bd_for_level(
        "L3",
        [
            BdWorkload(
                name="Lowest at capacity",
                bd_id="lowest",
                current_pending=2,
                capacity=2,
                level_counts={"L3": 1},
            ),
            BdWorkload(
                name="Available but ahead",
                bd_id="ahead",
                current_pending=0,
                capacity=2,
                level_counts={"L3": 2},
            ),
        ],
    )

    assert decision.assigned is False
    assert decision.blocked_reason == "level_balance_blocked_by_capacity"
    assert decision.excluded_reasons == {"lowest": "at_capacity"}


def test_selection_keeps_same_shop_total_ahead_of_pending_load() -> None:
    decision = select_bd_for_level(
        "L2",
        [
            BdWorkload(
                name="Busy",
                bd_id="busy",
                current_pending=8,
                capacity=10,
                total_assigned=0,
            ),
            BdWorkload(
                name="Available",
                bd_id="available",
                current_pending=1,
                capacity=10,
                total_assigned=100,
            ),
        ],
        assignment_key="sample-2",
    )

    assert decision.assigned_bd_id == "busy"


def test_seven_assignments_keep_three_eligible_bds_within_one() -> None:
    names = ("BD A", "BD B", "BD C")
    totals = Counter({name: 0 for name in names})
    last_assigned_at: dict[str, datetime | None] = {name: None for name in names}
    last_recipient: str | None = None

    for index in range(7):
        decision = select_bd_for_level(
            "L3",
            [
                BdWorkload(
                    name=name,
                    total_assigned=totals[name],
                    last_assigned_at=last_assigned_at[name],
                    last_received_levels=(
                        frozenset({"L3"}) if name == last_recipient else frozenset()
                    ),
                )
                for name in names
            ],
            assignment_key=f"sample-{index}",
        )
        assert decision.assigned_bd_name is not None
        selected = decision.assigned_bd_name
        totals[selected] += 1
        last_recipient = selected
        last_assigned_at[selected] = datetime(2026, 9, 10, index, tzinfo=UTC)
        assert max(totals.values()) - min(totals.values()) <= 1

    assert sorted(totals.values(), reverse=True) == [3, 2, 2]


def test_roster_requires_unique_real_identity_and_recipient() -> None:
    roster = [
        BdWorkload(
            name="BD A",
            bd_id="bd-a",
            recipient_open_id="ou-a",
        ),
        BdWorkload(
            name="BD B",
            bd_id="bd-b",
            recipient_open_id="ou-a",
        ),
    ]

    with pytest.raises(ValueError, match="unique"):
        validate_bd_roster(roster)


def test_three_bds_can_receive_each_level_once_without_imbalance() -> None:
    names = ("BD A", "BD B", "BD C")
    totals = Counter({name: 0 for name in names})
    level_counts = {name: Counter() for name in names}
    last_recipient_by_level: dict[str, str] = {}

    for level in reversed(("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")):
        for _ in names:
            decision = select_bd_for_level(
                level,
                [
                    BdWorkload(
                        name=name,
                        total_assigned=totals[name],
                        level_counts=level_counts[name],
                        last_received_levels=frozenset(
                            item_level
                            for item_level, recipient in last_recipient_by_level.items()
                            if recipient == name
                        ),
                    )
                    for name in names
                ],
            )
            assert decision.assigned_bd_name is not None
            selected = decision.assigned_bd_name
            totals[selected] += 1
            level_counts[selected][level] += 1
            last_recipient_by_level[level] = selected

    assert set(totals.values()) == {8}
    assert all(set(counts.values()) == {1} for counts in level_counts.values())
