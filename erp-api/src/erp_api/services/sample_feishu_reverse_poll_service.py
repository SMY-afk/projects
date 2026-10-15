from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from erp_api.services.feishu_sample_change import (
    normalize_feishu_business_fields,
)
from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS
from erp_api.services.sample_feishu_mapping_repository import SampleFeishuPollState


class FeishuSampleReversePollError(RuntimeError):
    pass


@dataclass(frozen=True)
class SampleFeishuReversePollResult:
    applied_count: int = 0
    duplicate_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    unmapped_count: int = 0


class SampleFeishuReversePollService:
    """Poll record metadata when Feishu event delivery cannot be used."""

    def __init__(
        self,
        application_repository,
        mapping_repository,
        feishu_clients: Sequence[object],
        *,
        recipient_provider=None,
    ):
        if not feishu_clients:
            raise ValueError("Feishu reverse poll requires at least one table client.")
        self._applications = application_repository
        self._mappings = mapping_repository
        self._feishu_clients = tuple(feishu_clients)
        self._recipient_provider = recipient_provider

    async def poll(
        self, *, full_scan: bool = True, now: datetime | None = None
    ) -> SampleFeishuReversePollResult:
        modified_since_date = None
        if not full_scan:
            current_time = now or datetime.now(UTC)
            modified_since_date = (current_time - timedelta(days=2)).date().isoformat()
        records = await self._list_record_snapshots(modified_since_date)
        states = await self._load_states([record.record_id for record in records])
        counts = {
            "applied": 0,
            "duplicate": 0,
            "unchanged": 0,
            "skipped": 0,
            "unmapped": 0,
        }
        recipient_open_ids = None
        for record in records:
            state = states.get(record.record_id)
            if state is None:
                counts["unmapped"] += 1
                continue
            modified_at = record.snapshot.modified_at
            if modified_at is None:
                raise FeishuSampleReversePollError(
                    "Feishu reverse poll record has no modified time."
                )
            if state.updated_at is not None and modified_at <= state.updated_at:
                counts["skipped"] += 1
                continue
            try:
                patch = normalize_feishu_business_fields(
                    record.snapshot.fields, set(BUSINESS_FIELDS)
                )
            except (TypeError, ValueError) as error:
                raise FeishuSampleReversePollError(
                    "Feishu reverse poll business field is invalid."
                ) from error
            changed_fields = {
                field_name: value
                for field_name, value in patch.fields.items()
                if state.business_fields[field_name] != value
            }
            if (
                "分配BD" in changed_fields
                and changed_fields["分配BD"] is None
                and state.business_fields["分配BD"]
            ):
                changed_fields.pop("分配BD")
            if not changed_fields:
                counts["unchanged"] += 1
                continue
            recipient_open_id = patch.assignment_recipient_open_id
            if (
                "分配BD" in changed_fields
                and changed_fields["分配BD"]
                and not recipient_open_id
                and self._recipient_provider is not None
            ):
                if recipient_open_ids is None:
                    recipient_open_ids = (
                        await self._recipient_provider.list_recipient_open_ids()
                    )
                recipient_open_id = recipient_open_ids.get(changed_fields["分配BD"])
            result = await self._applications.apply_feishu_business_fields(
                record_id=record.record_id,
                fields=changed_fields,
                event_id=_poll_event_id(record.record_id, modified_at, changed_fields),
                event_source="feishu_poll",
                actor_id=record.snapshot.modifier_id,
                actor_name=record.snapshot.modifier_name,
                assignment_recipient_open_id=(
                    recipient_open_id if "分配BD" in changed_fields else None
                ),
                occurred_at=modified_at,
            )
            if result not in {"applied", "duplicate", "unchanged"}:
                raise FeishuSampleReversePollError(
                    "Feishu reverse poll repository result is invalid."
                )
            counts[result] += 1
        return SampleFeishuReversePollResult(
            applied_count=counts["applied"],
            duplicate_count=counts["duplicate"],
            unchanged_count=counts["unchanged"],
            skipped_count=counts["skipped"],
            unmapped_count=counts["unmapped"],
        )

    async def _list_record_snapshots(
        self, modified_since_date: str | None
    ) -> tuple[object, ...]:
        records: list[object] = []
        record_ids: set[str] = set()
        for client in self._feishu_clients:
            table_records = await client.list_record_snapshots(
                modified_since_date=modified_since_date
            )
            for record in table_records:
                if record.record_id in record_ids:
                    raise FeishuSampleReversePollError(
                        "Feishu reverse poll record identity is duplicated across tables."
                    )
                record_ids.add(record.record_id)
                records.append(record)
        return tuple(records)

    async def _load_states(
        self, record_ids: list[str]
    ) -> dict[str, SampleFeishuPollState]:
        states: dict[str, SampleFeishuPollState] = {}
        for offset in range(0, len(record_ids), 500):
            states.update(
                await self._mappings.list_poll_states(record_ids[offset : offset + 500])
            )
        return states


def _poll_event_id(
    record_id: str, modified_at: datetime, fields: dict[str, str | None]
) -> str:
    body = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    field_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
    timestamp_ms = int(modified_at.timestamp() * 1000)
    candidate = f"feishu-poll:{record_id}:{timestamp_ms}:{field_hash}"
    if len(candidate) <= 255:
        return candidate
    digest = hashlib.sha256(candidate.encode()).hexdigest()
    return f"feishu-poll:{digest}"
