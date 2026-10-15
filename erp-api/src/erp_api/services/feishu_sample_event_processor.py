from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from erp_api.services.feishu_sample_change import normalize_feishu_business_fields
from erp_api.services.feishu_sample_event_receiver import (
    FeishuEventPayloadError,
    FeishuEventReceipt,
)
from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS

CALLBACK_METADATA_FIELDS = BUSINESS_FIELDS


class FeishuSampleEventProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuSampleEventProcessResult:
    applied_count: int = 0
    duplicate_count: int = 0
    unchanged_count: int = 0
    ignored_count: int = 0


class FeishuBusinessEventProcessor:
    def __init__(
        self,
        *,
        base_token: str,
        sample_processors: Mapping[str, FeishuSampleEventProcessor],
        assignment_table_id: str | None = None,
        assignment_notifier: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        self._base_token = base_token
        self._sample_processors = dict(sample_processors)
        self._assignment_table_id = assignment_table_id
        self._assignment_notifier = assignment_notifier

    async def process(self, receipt: FeishuEventReceipt) -> FeishuSampleEventProcessResult:
        if receipt.kind != "event" or receipt.file_token != self._base_token:
            raise FeishuEventPayloadError("Feishu callback target is invalid.")
        processor = self._sample_processors.get(receipt.table_id or "")
        if processor is not None:
            return await processor.process(receipt)
        if (
            receipt.table_id == self._assignment_table_id
            and self._assignment_notifier is not None
        ):
            try:
                await self._assignment_notifier()
            except Exception as error:
                raise FeishuSampleEventProcessingError(
                    "Assignment summary notification failed."
                ) from error
            return FeishuSampleEventProcessResult(ignored_count=1)
        raise FeishuEventPayloadError("Feishu callback target is invalid.")


class FeishuSampleEventProcessor:
    """Read changed Feishu records and atomically project business fields."""

    def __init__(self, repository, feishu_client, *, base_token: str, table_id: str):
        if not base_token or not table_id:
            raise ValueError("Feishu sample event target is incomplete.")
        self._repository = repository
        self._feishu = feishu_client
        self._base_token = base_token
        self._table_id = table_id
        self._business_fields_by_id: dict[str, str] | None = None
        self._metadata_lock = asyncio.Lock()

    async def process(
        self, receipt: FeishuEventReceipt
    ) -> FeishuSampleEventProcessResult:
        if (
            receipt.kind != "event"
            or receipt.file_token != self._base_token
            or receipt.table_id != self._table_id
        ):
            raise FeishuEventPayloadError("Feishu callback target is invalid.")
        if (
            receipt.event_id is None
            or receipt.occurred_at is None
            or receipt.operator_id is None
        ):
            raise FeishuEventPayloadError("Feishu callback identity is incomplete.")
        if not receipt.record_edits:
            return FeishuSampleEventProcessResult(ignored_count=1)

        business_fields_by_id = await self._field_mapping()
        counts = {"applied": 0, "duplicate": 0, "unchanged": 0, "ignored": 0}
        record_count = len(receipt.record_edits)
        for edit in receipt.record_edits:
            changed_names = {
                business_fields_by_id[field_id]
                for field_id in edit.changed_field_ids
                if field_id in business_fields_by_id
            }
            if not changed_names:
                counts["ignored"] += 1
                continue
            snapshot = await self._feishu.get_record_snapshot(edit.record_id)
            try:
                patch = normalize_feishu_business_fields(snapshot.fields, changed_names)
            except (TypeError, ValueError) as error:
                raise FeishuSampleEventProcessingError(
                    "Feishu record business field value is invalid."
                ) from error
            event_key = record_event_idempotency_key(
                receipt.event_id,
                edit.record_id,
                record_count=record_count,
            )
            result = await self._repository.apply_feishu_business_fields(
                record_id=edit.record_id,
                fields=patch.fields,
                event_id=event_key,
                event_source="feishu_callback",
                actor_id=receipt.operator_id,
                actor_name=(
                    snapshot.modifier_name
                    if snapshot.modifier_id == receipt.operator_id
                    else None
                ),
                assignment_recipient_open_id=(patch.assignment_recipient_open_id),
                occurred_at=receipt.occurred_at,
            )
            if result not in {"applied", "duplicate", "unchanged"}:
                raise FeishuSampleEventProcessingError(
                    "Feishu event repository returned an invalid result."
                )
            counts[result] += 1
        return FeishuSampleEventProcessResult(
            applied_count=counts["applied"],
            duplicate_count=counts["duplicate"],
            unchanged_count=counts["unchanged"],
            ignored_count=counts["ignored"],
        )

    async def _field_mapping(self) -> dict[str, str]:
        if self._business_fields_by_id is not None:
            return self._business_fields_by_id
        async with self._metadata_lock:
            if self._business_fields_by_id is None:
                metadata = await self._feishu.validate_required_fields(
                    CALLBACK_METADATA_FIELDS
                )
                mapping = {metadata[name].field_id: name for name in BUSINESS_FIELDS}
                if len(mapping) != len(BUSINESS_FIELDS):
                    raise FeishuSampleEventProcessingError(
                        "Feishu business field IDs are not unique."
                    )
                self._business_fields_by_id = mapping
        return self._business_fields_by_id


def record_event_idempotency_key(
    event_id: str, record_id: str, *, record_count: int
) -> str:
    if record_count <= 1:
        return event_id
    record_digest = hashlib.sha256(record_id.encode()).hexdigest()[:16]
    if len(event_id) + len(record_digest) + 1 <= 255:
        return f"{event_id}:{record_digest}"
    digest = hashlib.sha256(f"{event_id}\0{record_id}".encode()).hexdigest()
    return f"feishu:{digest}"
