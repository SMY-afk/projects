from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError


def _creator_shop_key(fields: dict[str, object]) -> tuple[str, str]:
    shop = fields.get("店铺名称")
    creator = fields.get("达人ID")
    return (
        shop.strip().casefold() if isinstance(shop, str) else "",
        creator.strip().lstrip("@").casefold() if isinstance(creator, str) else "",
    )


def _record_sort_key(record) -> tuple[int, str]:
    value = record.snapshot.fields.get("分配时间")
    timestamp = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return timestamp, record.record_id


async def _list_records(client, *, attempts: int = 5):
    for attempt in range(1, attempts + 1):
        try:
            return await client.list_record_snapshots()
        except FeishuSampleError:
            if attempt == attempts:
                raise
            await asyncio.sleep(attempt)
    raise AssertionError("unreachable")


def _duplicate_ids(records) -> tuple[str, ...]:
    grouped = defaultdict(list)
    for record in records:
        key = _creator_shop_key(record.snapshot.fields)
        if all(key):
            grouped[key].append(record)
    duplicate_ids: list[str] = []
    for matches in grouped.values():
        matches.sort(key=_record_sort_key, reverse=True)
        duplicate_ids.extend(record.record_id for record in matches[1:])
    return tuple(duplicate_ids)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_bd_assignment_record_table_id
    ):
        raise RuntimeError("Feishu assignment record cleanup is not configured.")
    client = FeishuAssignmentRecordClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_bd_assignment_record_table_id,
    )
    records = await _list_records(client)
    duplicate_ids = _duplicate_ids(records)
    print(
        json.dumps(
            {
                "status": "ready",
                "record_count": len(records),
                "duplicate_count": len(duplicate_ids),
                "apply": args.apply,
            }
        )
    )
    if not args.apply or not duplicate_ids:
        return
    deleted_count = 0
    for offset in range(0, len(duplicate_ids), 500):
        deleted = await client.batch_delete_records(duplicate_ids[offset : offset + 500])
        deleted_count += len(deleted)
    verified_records = await _list_records(client)
    remaining = _duplicate_ids(verified_records)
    if remaining:
        raise RuntimeError(
            f"Feishu assignment record cleanup left {len(remaining)} duplicate(s)."
        )
    print(
        json.dumps(
            {
                "status": "updated",
                "deleted_count": deleted_count,
                "verified_record_count": len(verified_records),
                "remaining_duplicate_count": 0,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
