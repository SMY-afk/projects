from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from erp_api.services.sample_assignment_record_fields import (
    is_cancelled_assignment_record,
)

LEVELS = tuple(f"L{index}" for index in range(8))
GMV_FIELDS = {level: f"{level} GMV（USD）" for level in LEVELS}
ROW_GMV_TOTAL_FIELD = "GMV总计（USD）"
SUMMARY_SOURCE = "ERP自动同步：分配记录 + PostgreSQL达人等级"
GLOBAL_COUNT_KEY = "等级数量总计"
GLOBAL_GMV_TOTAL_KEY = "GMV总计"
GLOBAL_GMV_AVERAGE_KEY = "GMV平均值"
ASSIGNMENT_SUMMARY_REVISION_KEY = "feishu:assignment-summary:revision"


@dataclass(frozen=True)
class AssignmentSummaryDetail:
    creator_level: str | None
    shop_name: str
    creator_gmv_minor: int | None = None
    sample_type: str = "free"


@dataclass(frozen=True)
class AssignmentSummarySyncResult:
    source_count: int
    updated_count: int
    created_count: int
    locked_count: int


class SampleAssignmentSummaryService:
    def __init__(
        self,
        repository,
        assignment_client,
        summary_client,
        *,
        allowed_shop_ids: Collection[UUID],
        bd_names: Sequence[str],
        bd_aliases: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sample_type: str = "free",
    ) -> None:
        self._repository = repository
        self._assignment_client = assignment_client
        self._summary_client = summary_client
        self._allowed_shop_ids = frozenset(allowed_shop_ids)
        self._bd_names = tuple(dict.fromkeys(name.strip() for name in bd_names if name.strip()))
        self._bd_aliases = {
            source.strip(): target.strip()
            for source, target in (bd_aliases or {}).items()
            if source.strip() and target.strip()
        }
        self._clock = clock
        if sample_type not in {"free", "refundable"}:
            raise ValueError("Assignment summary sample type is invalid")
        self._sample_type = sample_type
        if not self._allowed_shop_ids or not self._bd_names:
            raise ValueError("Assignment summary scope cannot be empty.")

    async def sync(self) -> AssignmentSummarySyncResult:
        source_records = await self._assignment_client.list_record_snapshots()
        assignments = self._parse_assignments(source_records)
        details = await self._repository.assignment_details(assignments)
        missing = set(assignments) - set(details)
        if missing:
            raise RuntimeError(
                f"Assignment summary level mapping is incomplete: {len(missing)} missing."
            )
        shop_names = await self._repository.list_shop_names(self._allowed_shop_ids)
        if len(shop_names) != len(self._allowed_shop_ids):
            raise RuntimeError("Assignment summary shop scope is incomplete.")
        assignments = {key: value for key, value in assignments.items()
                       if details[key].sample_type == self._sample_type}
        counts, row_gmv_totals, level_gmv_totals, gmv_counts = self._aggregate(
            assignments, details, shop_names
        )
        existing = await self._summary_client.list_record_snapshots()
        existing_by_key = self._index_summary_records(existing)
        sync_time = int(self._clock().timestamp() * 1000)
        updates: list[tuple[str, dict[str, object]]] = []
        creates: list[dict[str, object]] = []
        locked_count = 0
        for shop_name in shop_names:
            for bd_name in self._bd_names:
                key = f"{shop_name}｜{bd_name}"
                fields = self._system_fields(
                    counts,
                    row_gmv_totals,
                    shop_name,
                    bd_name,
                    sync_time,
                )
                record = existing_by_key.get(key)
                if record is None:
                    creates.append({"店铺｜BD": key, "人工锁定": False, **fields})
                    continue
                if _is_locked(record.snapshot.fields.get("人工锁定")):
                    locked_count += 1
                if not _same_business_fields(record.snapshot.fields, fields):
                    updates.append((record.record_id, fields))
        for key, fields in self._global_summary_fields(
            counts, level_gmv_totals, gmv_counts, sync_time
        ).items():
            record = existing_by_key.get(key)
            if record is not None and not _same_business_fields(
                record.snapshot.fields, fields
            ):
                updates.append((record.record_id, fields))
        if updates:
            await self._summary_client.batch_update_summary_records(updates)
        if creates:
            await self._summary_client.batch_create_summary_records(creates)
        return AssignmentSummarySyncResult(
            source_count=len(assignments),
            updated_count=len(updates),
            created_count=len(creates),
            locked_count=locked_count,
        )

    @staticmethod
    def split_assignment_types(assignments, details):
        free, paid = {}, {}
        for assignment_id, value in assignments.items():
            kind = details[assignment_id].sample_type
            if kind not in {"free", "refundable"}:
                raise RuntimeError("Assignment summary sample type is invalid")
            (paid if kind == "refundable" else free)[assignment_id] = value
        return free, paid

    def _parse_assignments(self, records) -> dict[UUID, tuple[str, str]]:
        assignments: dict[UUID, tuple[str, str]] = {}
        allowed_bds = set(self._bd_names)
        for record in records:
            fields = record.snapshot.fields
            if is_cancelled_assignment_record(fields):
                continue
            raw_id = fields.get("分配编号")
            try:
                assignment_id = UUID(raw_id) if isinstance(raw_id, str) else None
            except ValueError:
                assignment_id = None
            if assignment_id is None:
                continue
            raw_bd_name = fields.get("分配BD")
            raw_shop_name = fields.get("店铺名称")
            bd_name = self._bd_aliases.get(raw_bd_name, raw_bd_name)
            shop_name = _base_shop_name(raw_shop_name)
            if bd_name not in allowed_bds or not shop_name:
                raise RuntimeError("Assignment summary source contains an unexpected BD or shop.")
            if assignment_id in assignments:
                raise RuntimeError("Assignment summary source assignment ID is duplicated.")
            assignments[assignment_id] = (bd_name, shop_name)
        return assignments

    @staticmethod
    def _aggregate(
        assignments, details, shop_names
    ) -> tuple[Counter, Counter, Counter, Counter]:
        allowed_shops = set(shop_names)
        counts: Counter[tuple[str, str, str]] = Counter()
        row_gmv_totals: Counter[tuple[str, str, str]] = Counter()
        level_gmv_totals: Counter[str] = Counter()
        gmv_counts: Counter[str] = Counter()
        for assignment_id, (bd_name, source_shop) in assignments.items():
            detail = details[assignment_id]
            if detail.shop_name != source_shop or source_shop not in allowed_shops:
                raise RuntimeError("Assignment summary shop mapping does not match.")
            if detail.creator_level not in LEVELS:
                raise RuntimeError("Assignment summary creator level is missing or invalid.")
            counts[(source_shop, bd_name, detail.creator_level)] += 1
            if detail.creator_gmv_minor is not None and detail.creator_gmv_minor >= 0:
                row_gmv_totals[
                    (source_shop, bd_name, detail.creator_level)
                ] += detail.creator_gmv_minor
                level_gmv_totals[detail.creator_level] += detail.creator_gmv_minor
                gmv_counts[detail.creator_level] += 1
        return counts, row_gmv_totals, level_gmv_totals, gmv_counts

    @staticmethod
    def _index_summary_records(records):
        indexed = {}
        for record in records:
            key = record.snapshot.fields.get("店铺｜BD")
            if not isinstance(key, str) or not key:
                continue
            if key in indexed:
                raise RuntimeError("Assignment summary key is duplicated.")
            indexed[key] = record
        return indexed

    @staticmethod
    def _system_fields(
        counts,
        row_gmv_totals,
        shop_name: str,
        bd_name: str,
        sync_time: int,
    ):
        fields = {
            level: counts[(shop_name, bd_name, level)] for level in LEVELS
        }
        gmv_fields = {
            GMV_FIELDS[level]: _minor_to_major(
                row_gmv_totals[(shop_name, bd_name, level)]
            )
            for level in LEVELS
        }
        return {
            **fields,
            **gmv_fields,
            "店铺分配总计": sum(fields.values()),
            ROW_GMV_TOTAL_FIELD: _minor_to_major(
                sum(
                    row_gmv_totals[(shop_name, bd_name, level)]
                    for level in LEVELS
                )
            ),
            "最后同步时间": sync_time,
            "同步来源": SUMMARY_SOURCE,
        }

    @staticmethod
    def _global_summary_fields(counts, gmv_totals, gmv_counts, sync_time: int):
        level_counts = {
            level: sum(
                count
                for (_shop, _bd, item_level), count in counts.items()
                if item_level == level
            )
            for level in LEVELS
        }
        common = {"最后同步时间": sync_time, "同步来源": SUMMARY_SOURCE}
        return {
            GLOBAL_COUNT_KEY: {**level_counts, **common},
            GLOBAL_GMV_TOTAL_KEY: {
                **{
                    level: _minor_to_major(gmv_totals[level])
                    for level in LEVELS
                },
                **common,
            },
            GLOBAL_GMV_AVERAGE_KEY: {
                **{
                    level: _minor_to_major(
                        gmv_totals[level] / gmv_counts[level]
                    )
                    if gmv_counts[level]
                    else 0
                    for level in LEVELS
                },
                **common,
            },
        }


def _is_locked(value: object) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().casefold() in {
        "true",
        "1",
        "yes",
        "是",
    }


def _same_business_fields(existing: Mapping[str, object], expected: Mapping[str, object]) -> bool:
    for name, value in expected.items():
        if name == "最后同步时间":
            continue
        current = existing.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if Decimal(str(current)) != Decimal(str(value)):
                    return False
            except (TypeError, ValueError, ArithmeticError):
                return False
        elif current != value:
            return False
    return True


def _base_shop_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    for opening, closing in (("（", "）"), ("(", ")")):
        if opening in normalized and normalized.endswith(closing):
            return normalized.rsplit(opening, 1)[0].rstrip()
    return normalized


def _minor_to_major(value: float) -> float:
    return float(
        (Decimal(str(value)) / Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )
