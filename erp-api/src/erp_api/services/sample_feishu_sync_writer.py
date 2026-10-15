from __future__ import annotations

from datetime import datetime
from uuid import UUID

from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD
from erp_api.services.sample_feishu_sync_support import fields_match

_UPDATE_EXCLUDED_FIELDS = frozenset({"通知状态", "通知时间", "首次同步时间"})


async def write_sample_batch(
    *,
    tenant_id: UUID,
    shop_id: UUID,
    synced_at: datetime,
    progress,
    feishu,
    mappings,
    existing: dict[str, str],
    remote_fields: dict[str, dict[str, object]],
    batch: list[tuple[str, object, dict[str, object], str]],
) -> None:
    creates: list[tuple[UUID, dict[str, object], str]] = []
    updates: list[tuple[UUID, str, dict[str, object], str]] = []
    verified: list[tuple[UUID, str, str]] = []
    for sync_key, record, fields, digest in batch:
        record_id = existing.get(sync_key)
        if record_id is None:
            creates.append((record.application_id, fields, digest))
            continue
        update_fields = {
            key: value
            for key, value in fields.items()
            if key not in _UPDATE_EXCLUDED_FIELDS
        }
        if fields_match(update_fields, remote_fields[record_id]):
            verified.append((record.application_id, record_id, digest))
        else:
            updates.append((record.application_id, record_id, update_fields, digest))

    if creates:
        try:
            created = await feishu.batch_create_records(
                [fields for _application_id, fields, _digest in creates]
            )
        except Exception:
            await mappings.mark_failed(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=[application_id for application_id, _, _ in creates],
            )
            raise
        await mappings.attach_records(
            tenant_id=tenant_id,
            shop_id=shop_id,
            mappings=[
                (application_id, created[fields[SYNC_KEY_FIELD]])
                for application_id, fields, _digest in creates
            ],
        )
        progress.created_count += len(creates)
        await mappings.mark_synced(
            tenant_id=tenant_id,
            shop_id=shop_id,
            records=[
                (application_id, created[fields[SYNC_KEY_FIELD]], digest)
                for application_id, fields, digest in creates
            ],
            synced_at=synced_at,
        )
    if updates:
        try:
            updated = await feishu.batch_update_records(
                [(record_id, fields) for _, record_id, fields, _ in updates]
            )
        except Exception:
            await mappings.mark_failed(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=[application_id for application_id, _, _, _ in updates],
            )
            raise
        progress.updated_count += len(updated)
        await mappings.mark_synced(
            tenant_id=tenant_id,
            shop_id=shop_id,
            records=[
                (application_id, record_id, digest)
                for application_id, record_id, _, digest in updates
            ],
            synced_at=synced_at,
        )
    if verified:
        await mappings.mark_synced(
            tenant_id=tenant_id,
            shop_id=shop_id,
            records=verified,
            synced_at=synced_at,
        )
