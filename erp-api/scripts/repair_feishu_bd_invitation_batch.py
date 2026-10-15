from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from erp_api.core.config import get_settings
from erp_api.services.feishu_bd_invitation_collection_client import (
    FeishuBdInvitationCollectionClient,
)
from erp_api.services.sample_cooperation_parsing import normalize_account_name


@dataclass(frozen=True)
class ExistingRow:
    record_id: str
    auto_number: int
    creator_id: str
    bd_name: str
    original_submitter: str
    fields: dict[str, object]


@dataclass(frozen=True)
class RepairGroup:
    expected_creator_id: str
    keep_record_id: str
    keep_auto_number: int
    current_creator_ids: tuple[str, ...]
    delete_record_ids: tuple[str, ...]
    delete_auto_numbers: tuple[int, ...]
    edit_distance: int


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def build_repair_groups(
    rows: Sequence[ExistingRow], expected_creator_ids: Sequence[str]
) -> tuple[RepairGroup, ...]:
    current = tuple(normalize_account_name(row.creator_id) for row in rows)
    expected = tuple(normalize_account_name(value) for value in expected_creator_ids)
    if not current or not expected or any(not value for value in current + expected):
        raise ValueError("Repair input contains a blank creator ID.")
    limit = 6
    infinity = 10**9
    costs = [[infinity] * (len(current) + 1) for _ in range(len(expected) + 1)]
    choices = [[0] * (len(current) + 1) for _ in range(len(expected) + 1)]
    costs[0][0] = 0
    for expected_count in range(1, len(expected) + 1):
        for current_count in range(expected_count, len(current) + 1):
            for group_size in range(1, min(limit, current_count) + 1):
                prior = costs[expected_count - 1][current_count - group_size]
                if prior == infinity:
                    continue
                merged = "".join(current[current_count - group_size : current_count])
                candidate = prior + _edit_distance(
                    merged, expected[expected_count - 1]
                )
                if candidate < costs[expected_count][current_count]:
                    costs[expected_count][current_count] = candidate
                    choices[expected_count][current_count] = group_size
    if costs[-1][-1] == infinity:
        raise ValueError("Existing records cannot be aligned with the expected list.")
    groups: list[RepairGroup] = []
    expected_count = len(expected)
    current_count = len(current)
    while expected_count:
        group_size = choices[expected_count][current_count]
        if not group_size:
            raise ValueError("Repair alignment is incomplete.")
        start = current_count - group_size
        group_rows = rows[start:current_count]
        target = expected[expected_count - 1]
        groups.append(
            RepairGroup(
                target,
                group_rows[0].record_id,
                group_rows[0].auto_number,
                tuple(row.creator_id for row in group_rows),
                tuple(row.record_id for row in group_rows[1:]),
                tuple(row.auto_number for row in group_rows[1:]),
                _edit_distance("".join(current[start:current_count]), target),
            )
        )
        current_count = start
        expected_count -= 1
    groups.reverse()
    return tuple(groups)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected_file", type=Path)
    parser.add_argument("--first-auto", type=int, required=True)
    parser.add_argument("--last-auto", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    client = FeishuBdInvitationCollectionClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_bd_invitation_protection_table_id,
    )
    snapshots = await client.list_record_snapshots()
    rows = tuple(
        ExistingRow(
            record.record_id,
            int(record.snapshot.fields["自动编号"]),
            str(record.snapshot.fields.get("达人ID", "")),
            str(record.snapshot.fields.get("BD负责人", "")),
            str(record.snapshot.fields.get("原提交人", "")),
            record.snapshot.fields,
        )
        for record in snapshots
        if str(record.snapshot.fields.get("自动编号", "")).isdigit()
        and args.first_auto
        <= int(record.snapshot.fields["自动编号"])
        <= args.last_auto
    )
    rows = tuple(sorted(rows, key=lambda row: row.auto_number))
    expected_numbers = tuple(range(args.first_auto, args.last_auto + 1))
    if tuple(row.auto_number for row in rows) != expected_numbers:
        raise RuntimeError("Target auto-number range is not complete and contiguous.")
    if {row.bd_name for row in rows} != {"example-2b3220d55335"}:
        raise RuntimeError("Target batch contains an unexpected BD owner.")
    if {row.original_submitter for row in rows} != {"example-2b3220d55335"}:
        raise RuntimeError("Target batch contains an unexpected original submitter.")
    expected = tuple(
        line.strip()
        for line in args.expected_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    groups = build_repair_groups(rows, expected)
    updates = tuple(
        (group.keep_record_id, group.expected_creator_id, "example-2b3220d55335")
        for group in groups
        if normalize_account_name(group.current_creator_ids[0])
        != group.expected_creator_id
    )
    deletes = tuple(
        record_id for group in groups for record_id in group.delete_record_ids
    )
    if max(group.edit_distance for group in groups) > 3:
        raise RuntimeError("Repair alignment contains a high-distance row.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "created_at": timestamp,
        "scope": {"first_auto": args.first_auto, "last_auto": args.last_auto},
        "before_count": len(rows),
        "expected_count": len(expected),
        "update_count": len(updates),
        "delete_count": len(deletes),
        "rows": [asdict(row) for row in rows],
        "groups": [asdict(group) for group in groups],
    }
    evidence_path = args.output_dir / f"bd-invitation-repair-{timestamp}.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "mode": "apply" if args.apply else "preview",
        "before_count": len(rows),
        "expected_count": len(expected),
        "update_count": len(updates),
        "delete_count": len(deletes),
        "max_edit_distance": max(group.edit_distance for group in groups),
        "evidence_path": str(evidence_path),
        "changed_groups": [
            asdict(group)
            for group in groups
            if len(group.current_creator_ids) > 1 or group.edit_distance
        ],
    }
    if args.apply:
        if updates:
            await client.batch_update_split_records(updates)
        if deletes:
            await client.batch_delete_records(deletes)
        after = await client.list_record_snapshots()
        after_rows = tuple(
            record
            for record in after
            if str(record.snapshot.fields.get("自动编号", "")).isdigit()
            and args.first_auto
            <= int(record.snapshot.fields["自动编号"])
            <= args.last_auto
        )
        actual = tuple(
            normalize_account_name(record.snapshot.fields.get("达人ID"))
            for record in sorted(
                after_rows,
                key=lambda record: int(record.snapshot.fields["自动编号"]),
            )
        )
        intended = tuple(normalize_account_name(value) for value in expected)
        if actual != intended:
            raise RuntimeError("Repair readback does not match the expected list.")
        summary["after_count"] = len(after_rows)
        summary["readback_match"] = True
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(_run(_arguments()))
