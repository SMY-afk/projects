from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from erp_api.services.feishu_sample_batch_client import FEISHU_BATCH_RECORD_LIMIT


@dataclass(frozen=True)
class SampleFeishuGroupCleanupResult:
    updated_count: int
    deleted_count: int
    pending_record_ids: tuple[str, ...] = ()


async def delete_grouped_duplicate_records(
    *,
    feishu,
    mappings,
    tenant_id: UUID,
    shop_id: UUID,
    obsolete_platform_application_ids: frozenset[str],
    grouped_product_updates: tuple[tuple[str, tuple[str, ...]], ...] = (),
    allow_delete: bool = False,
) -> SampleFeishuGroupCleanupResult:
    platform_ids = tuple(sorted(obsolete_platform_application_ids))
    if any(not value or len(value) > 128 for value in platform_ids):
        raise ValueError("Grouped sample application identities are invalid.")
    if not platform_ids and not grouped_product_updates:
        return SampleFeishuGroupCleanupResult(0, 0)
    existing = await feishu.list_record_sync_key_map()
    updates = [
        (record_id, {"商品ID": list(product_ids)})
        for parent_id, product_ids in grouped_product_updates
        if (record_id := existing.get(f"{shop_id}:{parent_id}")) is not None
    ]
    updated_count = 0
    for offset in range(0, len(updates), FEISHU_BATCH_RECORD_LIMIT):
        batch = updates[offset : offset + FEISHU_BATCH_RECORD_LIMIT]
        updated_count += len(await feishu.batch_update_records(batch))
    record_ids = tuple(
        existing[sync_key]
        for platform_id in platform_ids
        if (sync_key := f"{shop_id}:{platform_id}") in existing
    )
    if not allow_delete:
        return SampleFeishuGroupCleanupResult(
            updated_count,
            0,
            pending_record_ids=record_ids,
        )
    deleted_count = 0
    for offset in range(0, len(record_ids), FEISHU_BATCH_RECORD_LIMIT):
        batch = record_ids[offset : offset + FEISHU_BATCH_RECORD_LIMIT]
        deleted = tuple(await feishu.batch_delete_records(batch))
        await mappings.detach_records(
            tenant_id=tenant_id,
            shop_id=shop_id,
            record_ids=deleted,
        )
        deleted_count += len(deleted)
    return SampleFeishuGroupCleanupResult(updated_count, deleted_count)
