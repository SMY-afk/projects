from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from backend.app.services.capture_logging import capture_log
from erp_api.services.sample_feishu_group_cleanup import (
    delete_grouped_duplicate_records,
)
from erp_api.services.sample_shop_sync_lock import SampleShopSyncBusyError


@dataclass(frozen=True)
class _ApplicationScope:
    application_ids: frozenset[UUID]


async def sync_enriched_applications(
    feishu_sync,
    *,
    tenant_id: UUID,
    shop_id: UUID,
    application_ids: frozenset[UUID],
    obsolete_platform_application_ids: frozenset[str] = frozenset(),
    grouped_product_updates: tuple[tuple[str, tuple[str, ...]], ...] = (),
    feishu=None,
    mappings=None,
    post_source_service=None,
    shop_sync_lock=None,
) -> dict[str, int | str]:
    if not application_ids:
        return {
            "feishu_created": 0,
            "feishu_updated": 0,
            "feishu_deleted": 0,
            "feishu_delete_pending": 0,
        }
    try:
        if post_source_service is None:
            sync = await feishu_sync.sync(
                tenant_id=tenant_id,
                shop_id=shop_id,
                application_ids=application_ids,
            )
        else:

            async def complete_pipeline():
                return await post_source_service.complete_after_source(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    source_type="official_api",
                    source_results=(_ApplicationScope(application_ids),),
                )

            if shop_sync_lock is None:
                pipeline_result = await complete_pipeline()
            else:
                async with shop_sync_lock.acquire(tenant_id, shop_id) as acquired:
                    if not acquired:
                        raise SampleShopSyncBusyError(
                            "A sample pipeline already owns this shop lock."
                        )
                    pipeline_result = await complete_pipeline()
            if getattr(pipeline_result, "status", None) == "skipped":
                return {
                    "feishu_created": 0,
                    "feishu_updated": 0,
                    "feishu_deleted": 0,
                    "feishu_delete_pending": 0,
                }
            sync = pipeline_result.feishu_result
        cleanup_updated = 0
        deleted = 0
        delete_pending = 0
        if obsolete_platform_application_ids or grouped_product_updates:
            if feishu is None or mappings is None:
                raise RuntimeError("Grouped Feishu cleanup is not configured.")
            cleanup = await delete_grouped_duplicate_records(
                feishu=feishu,
                mappings=mappings,
                tenant_id=tenant_id,
                shop_id=shop_id,
                obsolete_platform_application_ids=(obsolete_platform_application_ids),
                grouped_product_updates=grouped_product_updates,
            )
            cleanup_updated = cleanup.updated_count
            deleted = cleanup.deleted_count
            delete_pending = len(cleanup.pending_record_ids)
    except SampleShopSyncBusyError:
        capture_log(
            "ziniao_sample_time_feishu_sync_deferred",
            tenant_id=tenant_id,
            shop_id=shop_id,
            reason="shop_sync_busy",
        )
        return {
            "feishu_created": 0,
            "feishu_updated": 0,
            "feishu_deleted": 0,
            "feishu_delete_pending": 0,
            "feishu_deferred_reason": "shop_sync_busy",
        }
    except Exception as error:  # noqa: BLE001 -- retry on the next listener cycle
        error_type = type(error).__name__
        capture_log(
            "ziniao_sample_time_feishu_sync_failed",
            tenant_id=tenant_id,
            shop_id=shop_id,
            error_type=error_type,
        )
        return {
            "feishu_created": 0,
            "feishu_updated": 0,
            "feishu_deleted": 0,
            "feishu_delete_pending": 0,
            "feishu_error_type": error_type,
        }
    return {
        "feishu_created": getattr(sync, "created_count", 0),
        "feishu_updated": getattr(sync, "updated_count", 0) + cleanup_updated,
        "feishu_deleted": deleted,
        "feishu_delete_pending": delete_pending,
    }
