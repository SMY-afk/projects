from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from erp_api.services.sample_bd_assignment import AssignmentDecision, BdWorkload

if TYPE_CHECKING:
    from erp_api.services.sample_auto_assignment_service import PendingSampleAssignment


def compensation_decision(
    request: PendingSampleAssignment,
    roster: Sequence[BdWorkload],
    bd_name: str,
) -> AssignmentDecision | None:
    if request.creator_level is None or not request.category:
        return None
    member = next(
        (candidate for candidate in roster if candidate.name.casefold() == bd_name.casefold()),
        None,
    )
    if (
        member is None
        or not member.active
        or not member.test_enabled
        or member.current_pending >= member.capacity
        or (request.category not in member.categories and "*" not in member.categories)
        or not member.recipient_open_id
    ):
        return None
    return AssignmentDecision(
        member.name,
        request.creator_level,
        assigned_bd_id=member.bd_id or member.name,
        recipient_open_id=member.recipient_open_id,
        decision_reason="correction_compensation",
        creator_gmv_minor=(
            request.creator_gmv_minor
            if request.creator_gmv_minor is not None
            else request.estimated_level_gmv_minor
        ),
        estimated_level_gmv_minor=request.estimated_level_gmv_minor,
    )
