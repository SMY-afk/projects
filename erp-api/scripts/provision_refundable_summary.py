"""Create the separate paid resource mapping; remove only approved empty columns."""

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_summary_client import (
    FeishuAssignmentSummaryClient,
)
from erp_api.services.sample_assignment_summary_service import (
    GMV_FIELDS,
    ROW_GMV_TOTAL_FIELD,
)

TABLE_NAME = "买返样品资源总计"
REMOVABLE_FIELDS = [*(f"买返 L{index}" for index in range(8)), "买返样品总计"]
SUMMARY_FIELDS = {
    "店铺｜BD": 1, **{f"L{index}": 2 for index in range(8)},
    "店铺分配总计": 2, **{name: 2 for name in GMV_FIELDS.values()},
    ROW_GMV_TOTAL_FIELD: 2, "最后同步时间": 5, "人工锁定": 7, "同步来源": 1,
}


async def run(apply):
    settings = get_settings()
    options = {"app_id": settings.feishu_app_id,
               "app_secret": settings.feishu_app_secret.get_secret_value(),
               "base_token": settings.feishu_sample_base_token.get_secret_value()}
    base = options["base_token"]
    client = FeishuAssignmentSummaryClient(**options, table_id=settings.feishu_assignment_summary_table_id)
    token = await client.tenant_access_token()
    root = f"/open-apis/bitable/v1/apps/{base}"
    info = await client._request("GET", root, token=token)
    if info.get("app", {}).get("name") != "样品--副本":
        raise RuntimeError("Refundable summary Base identity mismatch")
    data = await client._request("GET", root + "/tables", token=token, params={"page_size": 100})
    if data.get("has_more"):
        raise RuntimeError("Base table inventory is incomplete")
    matches = [row for row in data.get("items", []) if row.get("name") == TABLE_NAME]
    if len(matches) > 1:
        raise RuntimeError("Refundable summary table name is duplicated")
    paid_id = matches[0]["table_id"] if matches else None
    metadata = await client.list_field_metadata()
    removable = [name for name in REMOVABLE_FIELDS if name in metadata]
    records = await client.list_record_snapshots() if removable else ()
    for record in records:
        for name in removable:
            if record.snapshot.fields.get(name) not in (None, "", []):
                raise RuntimeError("A new paid column contains data; preserve it for manual review")
    print(json.dumps({"apply": apply, "summary_table_id": paid_id,
                      "create_table": paid_id is None, "remove_empty_fields": removable,
                      "checked_original_rows": len(records)}, ensure_ascii=True), flush=True)
    if not apply:
        return
    if paid_id is None:
        result = await client._request("POST", root + "/tables", token=token, retry_mode="rate_limit",
            json={"table": {"name": TABLE_NAME, "default_view_name": "各店铺BD买返等级总计",
                            "fields": [{"field_name": "店铺｜BD", "type": 1}]}})
        paid_id = result.get("table_id") or result.get("table", {}).get("table_id")
        if not paid_id:
            raise RuntimeError("Refundable summary create outcome is unknown; inspect before retry")
    paid = FeishuAssignmentSummaryClient(**options, table_id=paid_id)
    actual = await paid.list_field_metadata()
    for name, kind in SUMMARY_FIELDS.items():
        if name in actual:
            if actual[name].field_type != kind:
                raise RuntimeError("Refundable summary field type mismatch")
            continue
        await paid._request("POST", paid._field_path(), token=token,
            json={"field_name": name, "type": kind,
                  **({"property": {"formatter": "0.00" if "GMV" in name else "0"}} if kind == 2 else {})})
    existing = {row.snapshot.fields.get("店铺｜BD") for row in await paid.list_record_snapshots()}
    global_rows = [{"店铺｜BD": key, "人工锁定": False} for key in (
        "等级数量总计", "GMV总计", "GMV平均值"
    ) if key not in existing]
    if global_rows:
        await paid.batch_create_summary_records(global_rows)
    reread = await paid.list_field_metadata()
    if any(name not in reread or reread[name].field_type != kind for name, kind in SUMMARY_FIELDS.items()):
        raise RuntimeError("Refundable summary schema readback mismatch")
    # Recheck immediately before irreversible field deletion, not just in preview.
    for record in await client.list_record_snapshots():
        if any(record.snapshot.fields.get(name) not in (None, "", []) for name in removable):
            raise RuntimeError("Original paid columns changed after preview; no deletion")
    for name in removable:
        await client._request("DELETE", client._field_path() + "/" + metadata[name].field_id, token=token)
    actual = await client.list_field_metadata()
    if any(name in actual for name in removable):
        raise RuntimeError("Original paid column removal readback failed")
    print(json.dumps({"summary_table_id": paid_id, "schema_verified": True,
                      "removed_empty_fields": removable}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args().apply))
