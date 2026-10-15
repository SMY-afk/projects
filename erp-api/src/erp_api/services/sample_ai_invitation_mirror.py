from __future__ import annotations

from dataclasses import dataclass

from erp_api.services.feishu_table_mirror_client import (
    FEISHU_MIRROR_BATCH_LIMIT,
    FeishuMirrorRecord,
)
from erp_api.services.sample_cooperation_parsing import plain_text

AI_INVITATION_CREATOR_FIELD = "达人ID"
AI_INVITATION_TIME_FIELD = "最近邀约时间"
AI_INVITATION_SOURCE_RECORD_FIELD = "源记录ID"


@dataclass(frozen=True)
class AiInvitationMirrorResult:
    source_count: int
    target_count: int
    created_count: int
    updated_count: int
    deleted_count: int


class SampleAiInvitationMirrorService:
    def __init__(self, source_client, target_client) -> None:
        self._source = source_client
        self._target = target_client

    async def validate(self) -> None:
        source_fields = await self._source.list_field_metadata()
        target_fields = await self._target.list_field_metadata()
        self._validate_types(
            source_fields,
            {
                AI_INVITATION_CREATOR_FIELD: 1,
                AI_INVITATION_TIME_FIELD: 5,
            },
            "source",
        )
        self._validate_types(
            target_fields,
            {
                AI_INVITATION_CREATOR_FIELD: 1,
                AI_INVITATION_TIME_FIELD: 5,
                AI_INVITATION_SOURCE_RECORD_FIELD: 1,
            },
            "target",
        )

    async def sync(self, *, dry_run: bool = False) -> AiInvitationMirrorResult:
        source_records = await self._source.list_records(
            field_names=(AI_INVITATION_CREATOR_FIELD, AI_INVITATION_TIME_FIELD)
        )
        target_records = await self._target.list_records(
            field_names=(
                AI_INVITATION_CREATOR_FIELD,
                AI_INVITATION_TIME_FIELD,
                AI_INVITATION_SOURCE_RECORD_FIELD,
            )
        )
        source = {
            record.record_id: self._source_fields(record) for record in source_records
        }
        target = self._target_index(target_records)
        creates = [
            {**fields, AI_INVITATION_SOURCE_RECORD_FIELD: source_id}
            for source_id, fields in source.items()
            if source_id not in target
        ]
        updates = [
            (
                target[source_id].record_id,
                {**fields, AI_INVITATION_SOURCE_RECORD_FIELD: source_id},
            )
            for source_id, fields in source.items()
            if source_id in target and self._target_fields(target[source_id]) != fields
        ]
        deletes = [
            record.record_id
            for source_id, record in target.items()
            if source_id not in source
        ]
        if not dry_run:
            await self._write_batches(self._target.batch_update, updates)
            await self._write_batches(self._target.batch_create, creates)
            await self._write_batches(self._target.batch_delete, deletes)
        return AiInvitationMirrorResult(
            len(source_records),
            len(target_records),
            len(creates),
            len(updates),
            len(deletes),
        )

    @staticmethod
    def _source_fields(record: FeishuMirrorRecord) -> dict[str, object]:
        creator_id = plain_text(record.fields.get(AI_INVITATION_CREATOR_FIELD))
        if not creator_id:
            raise RuntimeError(
                f"AI invitation source record is missing creator ID: {record.record_id}."
            )
        invitation_time = record.fields.get(AI_INVITATION_TIME_FIELD)
        if invitation_time is not None and (
            isinstance(invitation_time, bool) or not isinstance(invitation_time, int)
        ):
            raise RuntimeError(
                f"AI invitation source record has invalid time: {record.record_id}."
            )
        return {
            AI_INVITATION_CREATOR_FIELD: creator_id,
            AI_INVITATION_TIME_FIELD: invitation_time,
        }

    @staticmethod
    def _target_index(
        records: tuple[FeishuMirrorRecord, ...],
    ) -> dict[str, FeishuMirrorRecord]:
        indexed: dict[str, FeishuMirrorRecord] = {}
        for record in records:
            source_id = plain_text(record.fields.get(AI_INVITATION_SOURCE_RECORD_FIELD))
            if not source_id:
                continue
            if source_id in indexed:
                raise RuntimeError(
                    f"AI invitation mirror source ID is duplicated: {source_id}."
                )
            indexed[source_id] = record
        return indexed

    @classmethod
    def _target_fields(cls, record: FeishuMirrorRecord) -> dict[str, object]:
        invitation_time = record.fields.get(AI_INVITATION_TIME_FIELD)
        return {
            AI_INVITATION_CREATOR_FIELD: plain_text(
                record.fields.get(AI_INVITATION_CREATOR_FIELD)
            ),
            AI_INVITATION_TIME_FIELD: invitation_time,
        }

    @staticmethod
    async def _write_batches(method, rows: list) -> None:
        for offset in range(0, len(rows), FEISHU_MIRROR_BATCH_LIMIT):
            await method(rows[offset : offset + FEISHU_MIRROR_BATCH_LIMIT])

    @staticmethod
    def _validate_types(fields, expected: dict[str, int], label: str) -> None:
        invalid = {
            name: None if fields.get(name) is None else fields[name].field_type
            for name, field_type in expected.items()
            if fields.get(name) is None or fields[name].field_type != field_type
        }
        if invalid:
            raise RuntimeError(
                f"AI invitation mirror {label} fields are invalid: {invalid}."
            )
