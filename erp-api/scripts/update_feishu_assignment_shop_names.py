from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)

SHOP_DISPLAY_NAMES = {
    "fanfu toy tool": "fanfu toy tool（跨境3）",
    "akeleo fun toys": "Akeleo Fun Toys（跨境4）",
    "akeleo-drive": "Akeleo-Drive（跨境7）",
    "neopup": "NEOPUP（跨境12）",
    "akeleo toys": "Akeleo Toys（本土店）",
}


def _base_shop_name(value: str) -> str:
    normalized = value.strip()
    for expected in SHOP_DISPLAY_NAMES.values():
        suffix = expected[expected.rfind("（") :]
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)].rstrip()
    return normalized


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
        raise RuntimeError("Feishu assignment record table is not configured.")
    client = FeishuAssignmentRecordClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_bd_assignment_record_table_id,
    )
    records = await client.list_record_snapshots()
    updates = []
    unknown = []
    for record in records:
        value = record.snapshot.fields.get("店铺名称")
        if not isinstance(value, str) or not value.strip():
            unknown.append(
                {
                    "record_id": record.record_id,
                    "assignment_number": record.snapshot.fields.get("分配编号"),
                    "creator_id": record.snapshot.fields.get("达人ID"),
                }
            )
            continue
        base_name = _base_shop_name(value)
        expected = SHOP_DISPLAY_NAMES.get(base_name.casefold())
        if expected is None:
            unknown.append(
                {
                    "record_id": record.record_id,
                    "assignment_number": record.snapshot.fields.get("分配编号"),
                    "creator_id": record.snapshot.fields.get("达人ID"),
                    "shop_name": value,
                }
            )
        elif value != expected:
            updates.append((record.record_id, expected))
    print(
        json.dumps(
            {
                "status": "ready",
                "record_count": len(records),
                "update_count": len(updates),
                "unknown_records": unknown,
                "apply": args.apply,
            },
            ensure_ascii=False,
        )
    )
    if not args.apply:
        return
    for record_id, expected in updates:
        await client.update_assignment_record(record_id, {"店铺名称": expected})
    verified = await client.list_record_snapshots()
    mismatches = []
    for record in verified:
        value = record.snapshot.fields.get("店铺名称")
        if not isinstance(value, str):
            continue
        base_name = _base_shop_name(value)
        expected = SHOP_DISPLAY_NAMES.get(base_name.casefold())
        if expected is not None and value != expected:
            mismatches.append(record.record_id)
    if mismatches:
        raise RuntimeError(f"Shop name verification failed: {len(mismatches)}")
    print(
        json.dumps(
            {
                "status": "updated",
                "updated_count": len(updates),
                "verified_record_count": len(verified),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
