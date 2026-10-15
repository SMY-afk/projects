from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from erp_api.services.feishu_sample_batch_client import FEISHU_BATCH_RECORD_LIMIT
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD
from erp_api.services.sample_feishu_duplicate_cleanup import (
    find_duplicate_record_ids,
)
from erp_api.services.sample_feishu_incremental import (
    recently_synced,
    system_fields_hash,
)
from erp_api.services.sample_feishu_mapper import build_feishu_system_fields
from erp_api.services.sample_feishu_sync_support import index_records
from erp_api.services.sample_feishu_sync_writer import write_sample_batch
from erp_api.services.refundable_identity_guard import valid_unique_username


@dataclass(frozen=True)
class SampleFeishuSyncResult:
    source_count: int
    created_count: int
    updated_count: int
    delete_pending_count: int = 0


@dataclass
class _SyncProgress:
    source_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    delete_pending_count: int = 0


class SampleFeishuSyncService:
    """Synchronize committed PostgreSQL projections to Feishu system fields."""

    def __init__(
        self,
        source_repository,
        mapping_repository,
        audit_repository,
        feishu_clients,
        *,
        deduplication_started_at: datetime | None = None,
    ) -> None:
        if (
            deduplication_started_at is not None
            and deduplication_started_at.utcoffset() is None
        ):
            raise ValueError("Feishu deduplication start time must include a timezone.")
        self._source = source_repository
        self._mappings = mapping_repository
        self._audits = audit_repository
        self._feishu_clients = feishu_clients
        self._deduplication_started_at = (
            deduplication_started_at.astimezone(UTC)
            if deduplication_started_at is not None
            else None
        )

    async def sync(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: frozenset[UUID] | None = None,
    ) -> SampleFeishuSyncResult:
        started_at = datetime.now(UTC)
        run_id = await self._audits.start_feishu(
            tenant_id=tenant_id,
            shop_id=shop_id,
            started_at=started_at,
        )
        progress = _SyncProgress()
        feishu = self._feishu_clients.for_shop(shop_id)
        with feishu.capture_evidence() as trace:
            try:
                result = await self._sync_records(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    synced_at=started_at,
                    progress=progress,
                    feishu=feishu,
                    application_ids=application_ids,
                )
            except Exception as error:
                await self._audits.finish_feishu(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    run_id=run_id,
                    status="failed",
                    records_read=progress.source_count,
                    feishu_created=progress.created_count,
                    feishu_updated=progress.updated_count,
                    request_ids=trace.request_ids,
                    error_code=_failure_code(error),
                    finished_at=datetime.now(UTC),
                )
                raise
        await self._audits.finish_feishu(
            tenant_id=tenant_id,
            shop_id=shop_id,
            run_id=run_id,
            status="succeeded",
            records_read=progress.source_count,
            feishu_created=progress.created_count,
            feishu_updated=progress.updated_count,
            request_ids=trace.request_ids,
            error_code=None,
            finished_at=datetime.now(UTC),
        )
        return result

    async def _sync_records(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        synced_at: datetime,
        progress: _SyncProgress,
        feishu,
        application_ids: frozenset[UUID] | None,
    ) -> SampleFeishuSyncResult:
        if application_ids == frozenset():
            return SampleFeishuSyncResult(0, 0, 0)
        planned: list[tuple[str, object, dict[str, object], str]] = []
        desired_records: list[tuple[str, object]] = []
        seen_sync_keys: set[str] = set()
        cursor: UUID | None = None
        while True:
            records = await self._source.list_committed(
                tenant_id=tenant_id,
                shop_id=shop_id,
                after_application_id=cursor,
                limit=FEISHU_BATCH_RECORD_LIMIT,
                application_ids=application_ids,
            )
            if not records:
                break
            for record in records:
                if getattr(record, "sample_type", "free") == "refundable" and not valid_unique_username(record.creator_username):
                    continue
                fields = build_feishu_system_fields(record, synced_at=synced_at)
                sync_key = fields[SYNC_KEY_FIELD]
                if not isinstance(sync_key, str) or sync_key in seen_sync_keys:
                    raise RuntimeError(
                        "PostgreSQL sample sync key is invalid or duplicated."
                    )
                seen_sync_keys.add(sync_key)
                desired_records.append((sync_key, record))
                planned.append((sync_key, record, fields, system_fields_hash(fields)))
                progress.source_count = len(seen_sync_keys)
            next_cursor = records[-1].application_id
            if cursor is not None and next_cursor <= cursor:
                raise RuntimeError("PostgreSQL sample pagination did not advance.")
            cursor = next_cursor
            if len(records) < FEISHU_BATCH_RECORD_LIMIT:
                break

        if self._deduplication_started_at is not None:
            find_duplicate_record_ids(
                desired_records, {}, {}, started_at=self._deduplication_started_at
            )
        dirty = [
            item
            for item in planned
            if not recently_synced(item[1], item[3], now=synced_at)
        ]
        if not dirty:
            return SampleFeishuSyncResult(progress.source_count, 0, 0)

        full_audit_due = application_ids is None and any(
            record.feishu_record_id is not None
            and record.sync_status == "succeeded"
            and record.sync_hash == digest
            for _, record, _, digest in dirty
        )
        targeted = (
            not full_audit_due
            and len(dirty) <= 10
            and all(
                record.feishu_record_id
                and record.sync_hash
                and record.sync_status in {"succeeded", "failed"}
                for _, record, _, _ in dirty
            )
        )
        if targeted:
            existing: dict[str, str] = {}
            remote_fields: dict[str, dict[str, object]] = {}
            for sync_key, record, _fields, _digest in dirty:
                record_id = record.feishu_record_id
                snapshot = await feishu.get_record_snapshot(record_id)
                if snapshot.fields.get(SYNC_KEY_FIELD) != sync_key:
                    raise RuntimeError(
                        "PostgreSQL and Feishu record mappings conflict."
                    )
                existing[sync_key] = record_id
                remote_fields[record_id] = snapshot.fields
        else:
            existing, remote_fields = index_records(
                await feishu.list_record_snapshots()
            )
        existing_mappings: list[tuple[UUID, str]] = []
        for sync_key, record, _fields, _digest in dirty if targeted else planned:
            record_id = existing.get(sync_key)
            if record_id is None:
                if record.feishu_record_id is not None:
                    raise RuntimeError(
                        "Saved Feishu record is missing from the target table."
                    )
            elif record.feishu_record_id not in (None, record_id):
                raise RuntimeError("PostgreSQL and Feishu record mappings conflict.")
            elif record.feishu_record_id is None:
                existing_mappings.append((record.application_id, record_id))

        if self._deduplication_started_at is not None and not targeted:
            progress.delete_pending_count = len(
                find_duplicate_record_ids(
                    desired_records,
                    existing,
                    remote_fields,
                    started_at=self._deduplication_started_at,
                )
            )

        for batch in _chunks(existing_mappings):
            await self._mappings.attach_records(
                tenant_id=tenant_id,
                shop_id=shop_id,
                mappings=batch,
            )

        for batch in _chunks(dirty if targeted else planned):
            await write_sample_batch(
                tenant_id=tenant_id,
                shop_id=shop_id,
                synced_at=synced_at,
                progress=progress,
                feishu=feishu,
                mappings=self._mappings,
                existing=existing,
                remote_fields=remote_fields,
                batch=batch,
            )
        return SampleFeishuSyncResult(
            source_count=progress.source_count,
            created_count=progress.created_count,
            updated_count=progress.updated_count,
            delete_pending_count=progress.delete_pending_count,
        )


def _chunks(items: list, size: int = FEISHU_BATCH_RECORD_LIMIT):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _failure_code(error: Exception) -> str:
    if isinstance(error, FeishuSampleError):
        return error.error_code
    return type(error).__name__[:64]
