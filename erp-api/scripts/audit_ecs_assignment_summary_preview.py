"""Preview copied-Base assignment summary changes on ECS, without writes."""

import asyncio
import traceback
from collections import Counter

import httpx

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.feishu_assignment_record_client import FeishuAssignmentRecordClient
from erp_api.services.feishu_assignment_summary_client import FeishuAssignmentSummaryClient
from erp_api.services.feishu_sample_transport import FEISHU_API_BASE_URL
from erp_api.services.sample_assignment_summary_repository import (
    SampleAssignmentSummaryRepository,
)
from erp_api.services.sample_assignment_summary_service import (
    SampleAssignmentSummaryService,
    _is_locked,
    _same_business_fields,
)
async def main() -> None:
    settings = get_settings()
    print(
        f"CONFIG_SHOPS={len(settings.assignment_summary_shop_id_set)} "
        f"CONFIG_BDS={len(settings.assignment_summary_bd_names)} "
        f"SYNC_ENABLED={settings.feishu_assignment_summary_sync_enabled}"
    )
    database = Database(settings.database_url)
    options = {
        "app_id": settings.feishu_app_id,
        "app_secret": settings.feishu_app_secret.get_secret_value(),
        "base_token": settings.feishu_sample_base_token.get_secret_value(),
    }
    async with httpx.AsyncClient(base_url=FEISHU_API_BASE_URL, timeout=30) as client:
        assignment_client = FeishuAssignmentRecordClient(
            **options,
            table_id=settings.feishu_bd_assignment_record_table_id,
            client=client,
        )
        summary_client = FeishuAssignmentSummaryClient(
            **options,
            table_id=settings.feishu_assignment_summary_table_id,
            client=client,
        )
        service = SampleAssignmentSummaryService(
            SampleAssignmentSummaryRepository(database),
            assignment_client,
            summary_client,
            allowed_shop_ids=settings.assignment_summary_shop_id_set,
            bd_names=settings.assignment_summary_bd_names,
            bd_aliases=settings.feishu_assignment_summary_bd_aliases,
        )
        try:
            print("READ_SOURCE_ASSIGNMENTS")
            source = await assignment_client.list_record_snapshots()
            print(f"SOURCE_ROWS={len(source)}")
            assignments = service._parse_assignments(source)
            details = await service._repository.assignment_details(assignments)
            missing = set(assignments) - set(details)
            if missing:
                raise RuntimeError(f"MISSING_RDS_ASSIGNMENTS={len(missing)}")
            shop_names = await service._repository.list_shop_names(
                service._allowed_shop_ids
            )
            if len(shop_names) != len(service._allowed_shop_ids):
                raise RuntimeError("SHOP_SCOPE_INCOMPLETE")
            counts, row_gmv, level_gmv, gmv_counts = service._aggregate(
                assignments, details, shop_names
            )
            print("READ_TARGET_SUMMARY")
            existing = await summary_client.list_record_snapshots()
            indexed = service._index_summary_records(existing)
            update_count = create_count = locked_count = 0
            changed_fields: Counter[str] = Counter()
            sync_time = 0
            for shop_name in shop_names:
                for bd_name in service._bd_names:
                    key = f"{shop_name}｜{bd_name}"
                    fields = service._system_fields(
                        counts, row_gmv, shop_name, bd_name, sync_time
                    )
                    record = indexed.get(key)
                    if record is None:
                        create_count += 1
                    else:
                        locked_count += _is_locked(record.snapshot.fields.get("人工锁定"))
                        changed = not _same_business_fields(record.snapshot.fields, fields)
                        update_count += changed
                        if changed:
                            changed_fields.update(
                                name for name, value in fields.items()
                                if name != "最后同步时间"
                                and not _same_business_fields(
                                    record.snapshot.fields, {name: value}
                                )
                            )
            for key, fields in service._global_summary_fields(
                counts, level_gmv, gmv_counts, sync_time
            ).items():
                record = indexed.get(key)
                if record is not None:
                    changed = not _same_business_fields(record.snapshot.fields, fields)
                    update_count += changed
                    if changed:
                        changed_fields.update(
                            name for name, value in fields.items()
                            if name != "最后同步时间"
                            and not _same_business_fields(
                                record.snapshot.fields, {name: value}
                            )
                        )
            print(
                "ASSIGNMENT_SUMMARY_PREVIEW_OK "
                f"SOURCE_ROWS={len(source)} VALID_ASSIGNMENTS={len(assignments)} "
                f"RDS_MATCHED={len(details)} TARGET_ROWS={len(existing)} "
                f"SHOPS={len(shop_names)} BDS={len(service._bd_names)} "
                f"WOULD_UPDATE={update_count} WOULD_CREATE={create_count} "
                f"LOCKED={locked_count} WRITES=0"
            )
            print(f"CHANGED_FIELDS={dict(sorted(changed_fields.items()))}")
        finally:
            await database.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        origin = traceback.extract_tb(error.__traceback__)[-1]
        print(
            f"ASSIGNMENT_SUMMARY_PREVIEW_FAILED TYPE={type(error).__name__} "
            f"ORIGIN={origin.name}:{origin.lineno} "
            f"CODE={getattr(error, 'error_code', '-')} "
            f"REQUEST_ID={getattr(error, 'request_id', '-')}"
        )
        raise SystemExit(1) from None
