from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from erp_api.services.sample_bd_assignment import AssignmentDecision, BdWorkload


def apply_assignment_to_workloads(
    roster: Sequence[BdWorkload],
    decision: AssignmentDecision,
) -> tuple[BdWorkload, ...]:
    selected_id = (decision.assigned_bd_id or "").strip().casefold()
    selected_name = (decision.assigned_bd_name or "").strip().casefold()
    now = datetime.now(UTC)
    found = False
    updated = []
    for member in roster:
        member_id = (member.bd_id or member.name).strip().casefold()
        levels = set(member.last_received_levels)
        levels.discard(decision.creator_level)
        values = {"last_received_levels": frozenset(levels)}
        if member_id == selected_id or member.name.strip().casefold() == selected_name:
            found = True
            counts = dict(member.level_counts)
            counts[decision.creator_level] = counts.get(decision.creator_level, 0) + 1
            gmv_totals = dict(member.level_gmv_minor_totals)
            if decision.creator_gmv_minor is not None:
                gmv_totals[decision.creator_level] = (
                    gmv_totals.get(decision.creator_level, 0)
                    + decision.creator_gmv_minor
                )
            values.update(
                current_pending=member.current_pending + 1,
                assigned_today=member.assigned_today + 1,
                total_assigned=member.total_assigned + 1,
                level_counts=counts,
                level_gmv_minor_totals=gmv_totals,
                last_assigned_level=decision.creator_level,
                last_received_levels=frozenset({*levels, decision.creator_level}),
                last_assigned_at=now,
            )
        updated.append(replace(member, **values))
    if not found:
        raise RuntimeError("Assigned BD is missing from the workload roster.")
    return tuple(updated)
