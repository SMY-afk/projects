from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol


class LevelGmvWorkload(Protocol):
    name: str
    bd_id: str | None
    level_counts: Mapping[str, int]
    level_gmv_minor_totals: Mapping[str, int]


def valid_gmv(value: int | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def projected_round_spread(
    creator_level: str,
    candidates: Sequence[LevelGmvWorkload],
    *,
    selected: LevelGmvWorkload,
    creator_gmv_minor: int,
    estimated_gmv_minor: int,
) -> int:
    counts = [candidate.level_counts.get(creator_level, 0) for candidate in candidates]
    minimum_count = min(counts)
    maximum_count = max(counts)
    round_target = (
        minimum_count + 1 if minimum_count == maximum_count else maximum_count
    )
    totals = []
    selected_id = _candidate_id(selected)
    for candidate in candidates:
        count = candidate.level_counts.get(creator_level, 0)
        remaining_slots = max(0, round_target - count)
        projected_total = candidate.level_gmv_minor_totals.get(creator_level, 0)
        if _candidate_id(candidate) == selected_id:
            projected_total += creator_gmv_minor
            remaining_slots = max(0, remaining_slots - 1)
        projected_total += remaining_slots * estimated_gmv_minor
        totals.append(projected_total)
    return max(totals) - min(totals)


def _candidate_id(candidate: LevelGmvWorkload) -> str:
    return (candidate.bd_id or candidate.name).strip().casefold()
