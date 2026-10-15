from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", required=True)
    parser.add_argument("--creator", required=True)
    args = parser.parse_args()
    settings = get_settings()
    client = FeishuAssignmentRecordClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_bd_assignment_record_table_id,
    )
    shop = args.shop.strip().casefold()
    creator = args.creator.strip().lstrip("@").casefold()
    matches = []
    for record in await client.list_record_snapshots():
        fields = record.snapshot.fields
        actual_shop = str(fields.get("店铺名称") or "").strip().casefold()
        actual_creator = (
            str(fields.get("达人ID") or "").strip().lstrip("@").casefold()
        )
        if actual_shop == shop and actual_creator == creator:
            matches.append({"record_id": record.record_id, "fields": fields})
    print(json.dumps(matches, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
