from erp_api.services.sample_assignment_workload_delta import (
    apply_assignment_to_workloads,
)
from erp_api.services.sample_bd_assignment import BdWorkload, select_bd_for_level


def _member(
    name: str,
    *,
    level_count: int = 0,
    level_gmv_minor: int = 0,
    total_assigned: int = 0,
) -> BdWorkload:
    return BdWorkload(
        name=name,
        bd_id=name.casefold().replace(" ", "-"),
        recipient_open_id=f"ou-{name}",
        total_assigned=total_assigned,
        level_counts={"L5": level_count},
        level_gmv_minor_totals={"L5": level_gmv_minor},
    )


def test_current_creator_goes_to_smallest_projected_round_spread() -> None:
    decision = select_bd_for_level(
        "L5",
        (
            _member("BD A", level_gmv_minor=1_000_000),
            _member("BD B", level_gmv_minor=600_000),
            _member("BD C", level_gmv_minor=0),
        ),
        creator_gmv_minor=900_000,
        estimated_level_gmv_minor=500_000,
    )

    assert decision.assigned_bd_name == "BD C"
    assert decision.decision_reason == "selected_projected_gmv_balance"
    assert decision.projected_gmv_spread_minor == 600_000


def test_low_gmv_creator_can_offset_bd_with_high_historical_gmv() -> None:
    decision = select_bd_for_level(
        "L5",
        (
            _member("BD A", level_gmv_minor=1_000_000),
            _member("BD B", level_gmv_minor=0),
        ),
        creator_gmv_minor=100_000,
        estimated_level_gmv_minor=500_000,
    )

    assert decision.assigned_bd_name == "BD A"
    assert decision.projected_gmv_spread_minor == 600_000


def test_unfilled_round_slots_use_recent_level_average() -> None:
    decision = select_bd_for_level(
        "L5",
        (
            _member("BD A", level_count=2, level_gmv_minor=200_000),
            _member("BD B", level_count=2, level_gmv_minor=1_000_000),
            _member("BD C", level_count=4, level_gmv_minor=1_500_000),
        ),
        creator_gmv_minor=900_000,
        estimated_level_gmv_minor=500_000,
    )

    assert decision.assigned_bd_name == "BD A"
    assert decision.projected_gmv_spread_minor == 500_000


def test_hard_level_count_rule_wins_before_gmv_optimization() -> None:
    decision = select_bd_for_level(
        "L5",
        (
            _member("BD A", level_count=0, level_gmv_minor=2_000_000),
            _member("BD B", level_count=1, level_gmv_minor=0),
        ),
        creator_gmv_minor=900_000,
        estimated_level_gmv_minor=500_000,
    )

    assert decision.assigned_bd_name == "BD A"


def test_missing_current_gmv_uses_recent_level_average() -> None:
    decision = select_bd_for_level(
        "L5",
        (
            _member("BD A", level_gmv_minor=1_000_000),
            _member("BD B", level_gmv_minor=0),
        ),
        creator_gmv_minor=None,
        estimated_level_gmv_minor=500_000,
    )

    assert decision.creator_gmv_minor == 500_000


def test_in_run_assignment_carries_actual_gmv_into_next_decision() -> None:
    roster = (
        _member("BD A", level_gmv_minor=0),
        _member("BD B", level_gmv_minor=500_000),
    )
    first = select_bd_for_level(
        "L5",
        roster,
        creator_gmv_minor=800_000,
        estimated_level_gmv_minor=500_000,
    )
    updated = apply_assignment_to_workloads(roster, first)

    assert updated[0].level_gmv_minor_totals == {"L5": 800_000}
    next_decision = select_bd_for_level(
        "L5",
        updated,
        creator_gmv_minor=100_000,
        estimated_level_gmv_minor=500_000,
    )
    assert next_decision.assigned_bd_name == "BD B"
