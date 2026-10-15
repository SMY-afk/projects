from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fractions import Fraction

from erp_api.services.sample_projected_gmv import (
    projected_round_spread,
    valid_gmv,
)

CREATOR_LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7")
LEVEL_MINIMUM_GMV_MINOR = {
    "L0": 0,
    "L1": 100_000,
    "L2": 500_000,
    "L3": 2_500_000,
    "L4": 6_000_000,
    "L5": 15_000_000,
    "L6": 40_000_000,
    "L7": 150_000_000,
}


def classify_creator_level(gmv_minor: int) -> str:
    if gmv_minor < 0:
        raise ValueError("Creator GMV cannot be negative.")
    for level in reversed(CREATOR_LEVELS):
        if gmv_minor >= LEVEL_MINIMUM_GMV_MINOR[level]:
            return level
    raise AssertionError("L0 must cover every non-negative GMV value.")


@dataclass(frozen=True)
class BdWorkload:
    name: str
    bd_id: str | None = None
    recipient_open_id: str | None = None
    categories: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))
    current_pending: int = 0
    capacity: int = 10
    assigned_today: int = 0
    total_assigned: int = 0
    level_counts: Mapping[str, int] = field(default_factory=dict)
    level_gmv_minor_totals: Mapping[str, int] = field(default_factory=dict)
    last_assigned_level: str | None = None
    last_received_levels: frozenset[str] = field(default_factory=frozenset)
    last_assigned_at: datetime | None = None
    active: bool = True
    test_enabled: bool = True


@dataclass(frozen=True)
class AssignmentDecision:
    assigned_bd_name: str | None
    creator_level: str
    blocked_reason: str | None = None
    assigned_bd_id: str | None = None
    recipient_open_id: str | None = None
    decision_reason: str | None = None
    excluded_reasons: Mapping[str, str] = field(default_factory=dict)
    creator_gmv_minor: int | None = None
    estimated_level_gmv_minor: int | None = None
    projected_gmv_spread_minor: int | None = None

    @property
    def assigned(self) -> bool:
        return self.assigned_bd_name is not None


def select_bd_for_level(
    creator_level: str,
    candidates: Sequence[BdWorkload],
    *,
    category: str = "*",
    assignment_key: str = "default",
    creator_gmv_minor: int | None = None,
    estimated_level_gmv_minor: int | None = None,
) -> AssignmentDecision:
    if creator_level not in CREATOR_LEVELS:
        raise ValueError(f"Unsupported creator level: {creator_level}")
    if not category.strip() or not assignment_key.strip():
        raise ValueError("Assignment category and key must not be empty.")

    excluded: dict[str, str] = {}
    active = []
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        if not candidate.active or not candidate.test_enabled:
            excluded[candidate_id] = "inactive"
            continue
        active.append(candidate)
    if not active:
        return AssignmentDecision(
            None, creator_level, "no_active_bd", excluded_reasons=excluded
        )

    category_matched = []
    for candidate in active:
        candidate_id = _candidate_id(candidate)
        if category not in candidate.categories and "*" not in candidate.categories:
            excluded[candidate_id] = "category_mismatch"
            continue
        category_matched.append(candidate)
    if not category_matched:
        return AssignmentDecision(
            None, creator_level, "no_category_match", excluded_reasons=excluded
        )

    available = []
    for candidate in category_matched:
        candidate_id = _candidate_id(candidate)
        if candidate.current_pending >= candidate.capacity:
            excluded[candidate_id] = "at_capacity"
            continue
        available.append(candidate)
    if not available:
        return AssignmentDecision(
            None, creator_level, "all_at_capacity", excluded_reasons=excluded
        )

    minimum_level_count = min(
        candidate.level_counts.get(creator_level, 0)
        for candidate in category_matched
    )

    level_balanced_pool = [
        candidate
        for candidate in available
        if candidate.level_counts.get(creator_level, 0) == minimum_level_count
    ]
    if not level_balanced_pool:
        return AssignmentDecision(
            None,
            creator_level,
            "level_balance_blocked_by_capacity",
            excluded_reasons=excluded,
        )

    gmv_pool = level_balanced_pool
    projected_spread = None
    effective_gmv = valid_gmv(creator_gmv_minor)
    estimated_gmv = valid_gmv(estimated_level_gmv_minor)
    if effective_gmv is None:
        effective_gmv = estimated_gmv
    if estimated_gmv is None:
        estimated_gmv = effective_gmv
    if effective_gmv is not None and estimated_gmv is not None:
        projected = {
            _candidate_id(candidate): projected_round_spread(
                creator_level,
                category_matched,
                selected=candidate,
                creator_gmv_minor=effective_gmv,
                estimated_gmv_minor=estimated_gmv,
            )
            for candidate in level_balanced_pool
        }
        projected_spread = min(projected.values())
        gmv_pool = [
            candidate
            for candidate in level_balanced_pool
            if projected[_candidate_id(candidate)] == projected_spread
        ]
        if len(gmv_pool) < len(level_balanced_pool):
            for candidate in level_balanced_pool:
                if candidate not in gmv_pool:
                    excluded[_candidate_id(candidate)] = "projected_gmv_imbalance"

    rotation_alternatives = [
        candidate
        for candidate in gmv_pool
        if creator_level not in candidate.last_received_levels
    ]
    rotation_applied = bool(rotation_alternatives) and len(rotation_alternatives) < len(
        gmv_pool
    )
    rotation_overridden = not rotation_alternatives and any(
        creator_level in candidate.last_received_levels
        for candidate in gmv_pool
    )
    if rotation_applied:
        for candidate in gmv_pool:
            if creator_level in candidate.last_received_levels:
                excluded[_candidate_id(candidate)] = "recent_level_recipient"
    selection_pool = rotation_alternatives or gmv_pool
    minimum_total = min(candidate.total_assigned for candidate in selection_pool)
    balanced_pool = [
        candidate
        for candidate in selection_pool
        if candidate.total_assigned == minimum_total
    ]

    never_assigned = datetime.min.replace(tzinfo=UTC)

    def score(
        candidate: BdWorkload,
    ) -> tuple[int, Fraction, Fraction, datetime, str]:
        last_assigned_at = candidate.last_assigned_at or never_assigned
        if last_assigned_at.tzinfo is None:
            last_assigned_at = last_assigned_at.replace(tzinfo=UTC)
        load_ratio = Fraction(candidate.current_pending, candidate.capacity)
        daily_ratio = Fraction(candidate.assigned_today, candidate.capacity)
        return (
            candidate.level_counts.get(creator_level, 0),
            load_ratio,
            daily_ratio,
            last_assigned_at.astimezone(UTC),
            _candidate_id(candidate),
        )

    selected = min(balanced_pool, key=score)
    return AssignmentDecision(
        selected.name,
        creator_level,
        assigned_bd_id=_candidate_id(selected),
        recipient_open_id=selected.recipient_open_id,
        decision_reason=(
            "selected_projected_gmv_balance"
            if len(gmv_pool) < len(level_balanced_pool)
            else (
                "selected_level_balance_over_rotation"
                if rotation_overridden
                else (
                    "selected_level_rotation"
                    if rotation_applied
                    else (
                        "selected_level_balance"
                        if len(level_balanced_pool) < len(available)
                        else "selected"
                    )
                )
            )
        ),
        excluded_reasons=excluded,
        creator_gmv_minor=effective_gmv,
        estimated_level_gmv_minor=estimated_gmv,
        projected_gmv_spread_minor=projected_spread,
    )


def validate_bd_roster(candidates: Sequence[BdWorkload]) -> None:
    if not candidates:
        raise ValueError("BD roster must not be empty.")
    ids: set[str] = set()
    names: set[str] = set()
    recipients: set[str] = set()
    for candidate in candidates:
        candidate_id = _candidate_id(candidate)
        name = candidate.name.strip()
        recipient = (candidate.recipient_open_id or "").strip()
        if not name or not candidate_id or not recipient:
            raise ValueError("BD roster requires name, identity, and recipient.")
        if max(len(name), len(candidate_id), len(recipient)) > 255:
            raise ValueError("BD roster identity values are too long.")
        normalized_name = name.casefold()
        if candidate_id in ids or normalized_name in names or recipient in recipients:
            raise ValueError(
                "BD roster names, identities, and recipients must be unique."
            )
        if candidate.capacity <= 0 or candidate.current_pending < 0:
            raise ValueError("BD roster workload values are invalid.")
        if candidate.assigned_today < 0 or candidate.total_assigned < 0:
            raise ValueError("BD roster assignment counts are invalid.")
        if not candidate.categories or any(
            not item.strip() for item in candidate.categories
        ):
            raise ValueError("BD roster categories are invalid.")
        if any(value < 0 for value in candidate.level_counts.values()):
            raise ValueError("BD roster level counts are invalid.")
        if any(value < 0 for value in candidate.level_gmv_minor_totals.values()):
            raise ValueError("BD roster level GMV totals are invalid.")
        if not candidate.last_received_levels.issubset(CREATOR_LEVELS):
            raise ValueError("BD roster last received levels are invalid.")
        ids.add(candidate_id)
        names.add(normalized_name)
        recipients.add(recipient)


def _candidate_id(candidate: BdWorkload) -> str:
    return (candidate.bd_id or candidate.name).strip().casefold()
