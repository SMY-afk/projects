"""Read complete cooperation accounts without inferring a product-line source."""

import re
from collections import defaultdict
from datetime import date

from erp_api.services.feishu_creator_export_service import (
    FEISHU_MERGED_SOURCE,
    _creator_row,
    _field_text,
)
from scripts.daily_valid_creator_core import account_key
from scripts.daily_valid_creator_sample import sample_date

ACCOUNT_SOURCE_FIELDS = ("同意样品日期", "BD负责人", "帐号名称", "合作店铺")
MASTER_SEARCH_PAGE_SIZE = 500
COOPERATION_SHOPS = {**{f"跨境{number}店": f"跨境{number}" for number in (3, 4, 7, 12)},
                     **{f"跨境{number}": f"跨境{number}" for number in (3, 4, 7, 12)},
                     "本土2店": "本土店", "本土店": "本土店"}


async def _verify_source_identity(client):
    table = FEISHU_MERGED_SOURCE
    headers = {"Authorization": "Bearer " + await client.tenant_access_token()}
    root = f"/open-apis/bitable/v1/apps/{table.app_token}"
    app = await client.request_json("GET", root, retry_mode="idempotent", headers=headers)
    if app.get("data", {}).get("app", {}).get("name") != "达人建联总表":
        raise ValueError("Cooperation account Base identity mismatch")
    tables = await client.request_json("GET", root + "/tables", retry_mode="idempotent",
        headers=headers, params={"page_size": 100})
    if not any(row.get("table_id") == table.table_id and row.get("name") == "达人主表"
               for row in tables.get("data", {}).get("items", [])):
        raise ValueError("Cooperation account physical table identity mismatch")
    schema = await client.request_json("GET", root + f"/tables/{table.table_id}/fields",
        retry_mode="idempotent", headers=headers, params={"page_size": 100})
    actual = {row.get("field_name"): row.get("type") for row in schema.get("data", {}).get("items", [])}
    expected = {"同意样品日期": 5, "BD负责人": 1, "帐号名称": 1, "合作店铺": 4}
    if any(actual.get(name) != kind for name, kind in expected.items()):
        raise ValueError("Cooperation account four-field schema mismatch")
    return headers


async def _search_page(client, headers, *, page_size, page_token=""):
    table = FEISHU_MERGED_SOURCE
    params = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    response = await client.request_json(
        "POST", f"/open-apis/bitable/v1/apps/{table.app_token}/tables/{table.table_id}/records/search",
        retry_mode="idempotent", headers=headers, params=params,
        json={"field_names": list(ACCOUNT_SOURCE_FIELDS)},
    )
    data = response.get("data")
    if not isinstance(data, dict):
        raise TypeError("Cooperation account response is invalid")
    return data


async def read_accounts(client) -> dict:
    headers = await _verify_source_identity(client)
    table = FEISHU_MERGED_SOURCE
    rows, seen_ids, seen_pages = [], set(), set()
    expected, page_token, empty = None, "", 0
    while True:
        data = await _search_page(client, headers, page_size=MASTER_SEARCH_PAGE_SIZE,
                                  page_token=page_token)
        total, items = data.get("total"), data.get("items")
        if (type(total) is not int or total < 0 or not isinstance(items, list)
                or not isinstance(data.get("has_more"), bool)):
            raise ValueError("Cooperation account response is invalid")
        if expected is not None and total != expected:
            raise ValueError("Cooperation account total changed during pagination")
        expected = total
        for item in items:
            record_id, fields = item.get("record_id"), item.get("fields")
            if (not isinstance(record_id, str) or not record_id
                    or record_id in seen_ids or not isinstance(fields, dict)):
                raise ValueError("Cooperation account record is invalid or duplicated")
            seen_ids.add(record_id)
            if all(not _field_text(fields.get(name)) for name in ACCOUNT_SOURCE_FIELDS):
                empty += 1
                continue
            rows.append({**_creator_row(item),
                         "cooperationShop": _field_text(fields.get("合作店铺"))})
        if not data["has_more"]:
            break
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token or page_token in seen_pages:
            raise ValueError("Cooperation account pagination is incomplete")
        seen_pages.add(page_token)
    if len(seen_ids) != expected or len(rows) + empty != expected:
        raise ValueError("Cooperation account capture is incomplete")
    final = await _search_page(client, headers, page_size=1)
    if (type(final.get("total")) is not int or not isinstance(final.get("items"), list)
            or not isinstance(final.get("has_more"), bool)):
        raise ValueError("Cooperation account final response is invalid")
    if final.get("total") != expected:
        raise ValueError("Cooperation account total changed during pagination")
    if len(final["items"]) != min(1, expected):
        raise ValueError("Cooperation account final record is incomplete")
    if final["items"] and final["items"][0].get("record_id") not in seen_ids:
        raise ValueError("Cooperation account final record changed during pagination")
    return {"total": len(rows), "rows": rows, "captured_total": expected,
            "empty_placeholders": empty, "scope": "physical_table",
            "physical_table_id": table.table_id, "terminal_confirmed": True,
            "unique_record_ids": True, "final_total": final["total"]}


def select_accounts(rows, sample_window):
    grouped = defaultdict(list)
    latest_declared = {}
    for row in rows:
        key = account_key(row.get("accountName"))
        if str(row.get("cooperationShop") or "").strip():
            approved = sample_date(row.get("sampleApprovedDate"), sample_window) or date.min
            latest_declared[key] = max(latest_declared.get(key, date.min), approved)
    for ordinal, row in enumerate(rows):
        key = account_key(row.get("accountName"))
        if not key:
            continue
        approved = sample_date(row.get("sampleApprovedDate"), sample_window)
        raw_shops = str(row.get("cooperationShop") or "").strip()
        if raw_shops:
            shops = {COOPERATION_SHOPS[label.strip()] for label in re.split(r"[；;,，、\n]", raw_shops)
                     if label.strip() in COOPERATION_SHOPS}
        elif key not in latest_declared or (approved or date.min) > latest_declared[key]:
            shops = {""}
        else:
            shops = set()
        for shop in shops:
            grouped[(key, shop)].append((approved, ordinal, row))
    selected, conflicts = {}, 0
    for key, candidates in grouped.items():
        ordered = sorted(candidates, key=lambda item: (item[0] or date.min, item[1]))
        latest_day, _, latest = ordered[-1]
        with_bd = [item for item in ordered if str(item[2].get("bdOwner") or "").strip()]
        owners = {str(item[2].get("bdOwner") or "").strip() for item in ordered} - {""}
        conflicts += len(owners) > 1
        selected[key] = {"account": str(latest["accountName"]).strip(),
                         "bd": str(with_bd[-1][2]["bdOwner"]).strip() if with_bd else "",
                         "sample_day": latest_day, "conflict": len(owners) > 1}
    if not selected:
        raise ValueError("No usable Feishu creator accounts")
    return selected, conflicts
