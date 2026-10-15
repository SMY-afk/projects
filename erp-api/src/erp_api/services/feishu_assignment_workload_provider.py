from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from erp_api.services.sample_assignment_record_fields import (
    is_cancelled_assignment_record,
)
from erp_api.services.sample_bd_assignment import CREATOR_LEVELS, BdWorkload


@dataclass(frozen=True)
class AssignmentWorkloadDetail:
    shop_id: UUID
    creator_level: str | None
    creator_gmv_minor: int | None = None
    sample_type: str = "free"


class AssignmentWorkloadDetails(Protocol):
    async def assignment_workload_details(
        self, assignment_ids: Sequence[UUID]
    ) -> dict[UUID, AssignmentWorkloadDetail]: ...


class FeishuAssignmentWorkloadProvider:
    """Build BD allocation counts from the existing Feishu assignment records."""

    def __init__(
        self,
        assignment_client,
        details: AssignmentWorkloadDetails,
        *,
        bd_aliases: Mapping[str, str] | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._assignment_client = assignment_client
        self._details = details
        self._bd_aliases = {
            source.strip().casefold(): target.strip().casefold()
            for source, target in (bd_aliases or {}).items()
            if source.strip() and target.strip()
        }
        self._clock = clock

    async def enrich(
        self,
        shop_id: UUID,
        roster: Sequence[BdWorkload],
        *,
        sample_type: str = "free",
    ) -> tuple[BdWorkload, ...]:
        if sample_type not in {"free", "refundable"}:
            raise ValueError("Assignment workload sample type is invalid")
        records = await self._assignment_client.list_record_snapshots()
        parsed = tuple(filter(None, (_parse_record(record) for record in records)))
        assignment_ids = tuple(item.assignment_id for item in parsed)
        details = await self._details.assignment_workload_details(assignment_ids)
        missing = set(assignment_ids) - set(details)
        if missing:
            raise RuntimeError(
                f"Assignment workload level mapping is incomplete: {len(missing)} missing."
            )

        names_by_key: dict[str, str] = {}
        for member in roster:
            key = self._canonical_bd_name(member.name)
            if key in names_by_key:
                raise RuntimeError("Assignment workload BD aliases are ambiguous.")
            names_by_key[key] = member.name
        total: Counter[str] = Counter()
        today: Counter[str] = Counter()
        by_level: dict[str, Counter[str]] = defaultdict(Counter)
        by_level_gmv: dict[str, Counter[str]] = defaultdict(Counter)
        latest: dict[str, tuple[datetime, str]] = {}
        latest_by_level: dict[str, tuple[datetime, str]] = {}
        today_start = self._clock().astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for item in parsed:
            detail = details[item.assignment_id]
            if detail.sample_type not in {"free", "refundable"}:
                raise RuntimeError("Assignment workload source sample type is invalid")
            if detail.shop_id != shop_id or detail.sample_type != sample_type:
                continue
            bd_name = names_by_key.get(self._canonical_bd_name(item.bd_name))
            if bd_name is None:
                continue
            if detail.creator_level not in CREATOR_LEVELS:
                raise RuntimeError(
                    "Assignment workload creator level is missing or invalid."
                )
            total[bd_name] += 1
            by_level[bd_name][detail.creator_level] += 1
            if detail.creator_gmv_minor is not None and detail.creator_gmv_minor >= 0:
                by_level_gmv[bd_name][detail.creator_level] += detail.creator_gmv_minor
            if item.assigned_at >= today_start:
                today[bd_name] += 1
            current = latest.get(bd_name)
            if current is None or item.assigned_at > current[0]:
                latest[bd_name] = (item.assigned_at, detail.creator_level)
            level_current = latest_by_level.get(detail.creator_level)
            if level_current is None or item.assigned_at > level_current[0]:
                latest_by_level[detail.creator_level] = (
                    item.assigned_at,
                    bd_name,
                )

        return tuple(
            replace(
                member,
                assigned_today=today[member.name],
                total_assigned=total[member.name],
                level_counts=dict(by_level[member.name]),
                level_gmv_minor_totals=dict(by_level_gmv[member.name]),
                last_assigned_at=(latest.get(member.name) or (None, None))[0],
                last_assigned_level=(latest.get(member.name) or (None, None))[1],
                last_received_levels=frozenset(
                    level
                    for level, (_assigned_at, bd_name) in latest_by_level.items()
                    if bd_name == member.name
                ),
            )
            for member in roster
        )

    def _canonical_bd_name(self, value: str) -> str:
        normalized = value.strip().casefold()
        return self._bd_aliases.get(normalized, normalized)


@dataclass(frozen=True)
class _AssignmentRecord:
    assignment_id: UUID
    bd_name: str
    assigned_at: datetime


def _parse_record(record) -> _AssignmentRecord | None:
    fields = record.snapshot.fields
    if is_cancelled_assignment_record(fields):
        return None
    raw_id = fields.get("分配编号")
    try:
        assignment_id = UUID(raw_id) if isinstance(raw_id, str) else None
    except ValueError:
        assignment_id = None
    if assignment_id is None:
        return None
    bd_name = fields.get("分配BD")
    if not isinstance(bd_name, str) or not bd_name.strip():
        raise RuntimeError("Assignment workload BD name is missing.")
    assigned_at = _timestamp(fields.get("分配时间"))
    if assigned_at is None:
        raise RuntimeError("Assignment workload assignment time is missing.")
    return _AssignmentRecord(assignment_id, bd_name.strip(), assigned_at)


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / 1000 if abs(float(value)) >= 100_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
