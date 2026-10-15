from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from erp_api.services.sample_bd_assignment import AssignmentDecision, BdWorkload

if TYPE_CHECKING:
    from erp_api.services.sample_auto_assignment_service import (
        PendingSampleAssignment,
    )


def keep_creator_with_existing_bd(
    request: PendingSampleAssignment,
    roster: Sequence[BdWorkload],
    bd_name: str,
) -> AssignmentDecision:
    if request.creator_level is None:
        return AssignmentDecision(None, "unclassified", "invalid_gmv")
    if request.category is None or not request.category.strip():
        return AssignmentDecision(None, request.creator_level, "unknown_category")
    member = next(
        (
            candidate
            for candidate in roster
            if candidate.name.strip().casefold() == bd_name.strip().casefold()
        ),
        None,
    )
    if member is None:
        return AssignmentDecision(
            None,
            request.creator_level,
            "same_creator_bd_unavailable",
            excluded_reasons={bd_name: "not_in_roster"},
        )
    member_id = member.bd_id or member.name
    if not member.active or not member.test_enabled:
        return AssignmentDecision(
            None,
            request.creator_level,
            "same_creator_bd_unavailable",
            excluded_reasons={member_id: "inactive"},
        )
    if request.category not in member.categories and "*" not in member.categories:
        return AssignmentDecision(
            None,
            request.creator_level,
            "same_creator_bd_unavailable",
            excluded_reasons={member_id: "category_not_allowed"},
        )
    if member.current_pending >= member.capacity:
        return AssignmentDecision(
            None,
            request.creator_level,
            "same_creator_bd_unavailable",
            excluded_reasons={member_id: "at_capacity"},
        )
    return AssignmentDecision(
        member.name,
        request.creator_level,
        assigned_bd_id=member_id,
        recipient_open_id=member.recipient_open_id,
        decision_reason="same_creator_existing_assignment",
        creator_gmv_minor=(
            request.creator_gmv_minor
            if request.creator_gmv_minor is not None
            else request.estimated_level_gmv_minor
        ),
        estimated_level_gmv_minor=request.estimated_level_gmv_minor,
    )
