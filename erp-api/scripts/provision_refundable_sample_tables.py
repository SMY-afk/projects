"""Preview/apply/read back only the approved refundable schema additions."""

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_assignment_record_fields import ASSIGNMENT_RECORD_SCHEMA

TABLE_NAME = "买返样品分配表"


async def ensure_fields(client, definitions, apply):
    actual = await client.list_field_metadata()
    missing = []
    for name, kind in definitions:
        current = actual.get(name)
        if current is not None:
            if current.field_type != kind:
                raise RuntimeError("Existing Feishu field type conflicts with refundable schema")
            continue
        missing.append(name)
        if apply:
            await client.create_field_definition(
                field_name=name, field_type=kind, ui_type="Number" if kind == 2 else "Text" if kind == 1 else "DateTime",
                field_property={"formatter": "0"} if kind == 2 else {"date_formatter": "yyyy-MM-dd HH:mm"} if kind == 5 else {},
            )
    if apply:
        reread = await client.list_field_metadata()
        if any(name not in reread or reread[name].field_type != kind for name, kind in definitions):
            raise RuntimeError("Refundable schema readback failed")
    return missing


async def run(apply):
    settings = get_settings()
    options = {"app_id": settings.feishu_app_id,
               "app_secret": settings.feishu_app_secret.get_secret_value(),
               "base_token": settings.feishu_sample_base_token.get_secret_value()}
    base = options["base_token"]
    master = FeishuSampleBatchClient(**options, table_id=settings.feishu_sample_table_id)
    token = await master.tenant_access_token()
    info = await master._request("GET", f"/open-apis/bitable/v1/apps/{base}", token=token)
    if info.get("app", {}).get("name") != "样品--副本":
        raise RuntimeError("Refundable target Base identity is not 样品--副本")
    tables, cursor = [], None
    while True:
        data = await master._request("GET", f"/open-apis/bitable/v1/apps/{base}/tables", token=token,
                                     params={"page_size": 100, **({"page_token": cursor} if cursor else {})})
        tables.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        next_cursor = data.get("page_token")
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("Feishu table pagination is incomplete")
        cursor = next_cursor
    matches = [item for item in tables if item.get("name") == TABLE_NAME]
    if len(matches) > 1:
        raise RuntimeError("Refundable assignment table name is duplicated")
    table_id = matches[0]["table_id"] if matches else None
    changes = []
    if table_id is None:
        changes.append("create_table:" + TABLE_NAME)
        if apply:
            result = await master._request("POST", f"/open-apis/bitable/v1/apps/{base}/tables", token=token,
                json={"table": {"name": TABLE_NAME, "default_view_name": "买返样品分配",
                                "fields": [{"field_name": "分配编号", "type": 1}]}}, retry_mode="rate_limit")
            table_id = result.get("table_id") or result.get("table", {}).get("table_id")
            if not table_id:
                raise RuntimeError("Refundable table create outcome is unknown; inspect before retrying")
    if table_id:
        paid = FeishuSampleBatchClient(**options, table_id=table_id)
        changes.extend("assignment_field:" + name for name in await ensure_fields(paid, ASSIGNMENT_RECORD_SCHEMA, apply))
    shop_tables = {settings.feishu_sample_table_id, *settings.feishu_sample_shop_table_ids.values()}
    if len(shop_tables) != 5:
        raise RuntimeError("Refundable sample table scope is not exactly five")
    for sample_table in sorted(shop_tables):
        client = FeishuSampleBatchClient(**options, table_id=sample_table)
        changes.extend(f"sample_type:{sample_table}:{name}" for name in await ensure_fields(client, [("样品类型", 1)], apply))
    print(json.dumps({"apply": apply, "base_name": "样品--副本", "assignment_table_id": table_id,
                      "changes": changes, "sample_table_count": 5}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args().apply))
