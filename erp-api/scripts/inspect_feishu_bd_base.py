from __future__ import annotations

import asyncio
import json
import sys

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient


async def main() -> None:
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        raise RuntimeError("Feishu sample connection is not configured.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    client = FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=base_token,
        table_id=settings.feishu_sample_table_id or "not-configured",
    )
    token = await client.tenant_access_token()
    data = await client._request(
        "GET",
        f"/open-apis/bitable/v1/apps/{base_token}/tables",
        token=token,
        params={"page_size": 100},
    )
    items = data.get("items")
    if not isinstance(items, list):
        raise TypeError("Feishu table list is invalid.")
    for item in items:
        if isinstance(item, dict):
            table_id = item.get("table_id")
            table_name = item.get("name")
            print(json.dumps({"name": table_name, "table_id": table_id}))
            if len(sys.argv) == 2 and sys.argv[1] == table_id:
                detail = FeishuSampleBatchClient(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret.get_secret_value(),
                    base_token=base_token,
                    table_id=table_id,
                )
                fields = await detail.list_field_metadata()
                print(
                    json.dumps(
                        {
                            "fields": [
                                {"name": name, "type": metadata.field_type}
                                for name, metadata in fields.items()
                            ]
                        }
                    )
                )
                records = await detail.list_record_snapshots()
                print(
                    json.dumps(
                        {
                            "records": [
                                {
                                    "record_id": record.record_id,
                                    "fields": _redact(record.snapshot.fields),
                                }
                                for record in records
                            ]
                        }
                    )
                )


def _redact(value):
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "***" if key in {"id", "open_id", "user_id"} else _redact(item)
            for key, item in value.items()
        }
    return value


if __name__ == "__main__":
    asyncio.run(main())
