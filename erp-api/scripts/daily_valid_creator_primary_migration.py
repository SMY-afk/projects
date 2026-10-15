"""Authorized primary-column cutover; keep account values and all record IDs."""
import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from redis.asyncio import Redis

from erp_api.core.config import get_settings
from erp_api.services.sample_business_readiness import (
    SampleBusinessReadiness,
    _valid_creator_batch_date,
)
from scripts.daily_valid_creator_io import (
    BASE,
    FIELD_TYPES,
    TABLE,
    feishu_client,
    target_rows,
    verify_target_identity,
)

BACKUP_NAME = "账号名称（迁移备份）"


def account_copy(rows):
    seen, updates = set(), []
    for row in rows:
        record_id = row.get("record_id")
        account = row.get("fields", {}).get("账号名称")
        if not record_id or record_id in seen:
            raise ValueError("Invalid record identity during primary migration")
        if not isinstance(account, str) or not account.strip():
            raise ValueError("Invalid account identity during primary migration")
        seen.add(record_id)
        updates.append({"record_id": record_id, "fields": {"产品线": account}})
    return updates


def comparable_rows(rows, ignored):
    return {row["record_id"]: {name: value for name, value in row["fields"].items()
        if name not in ignored} for row in rows}


def save_snapshot(path, fields, records):
    payload = {"base": BASE, "table": TABLE, "fields": fields, "records": records}
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    with path.open(encoding="utf-8") as stream:
        if json.load(stream) != payload:
            raise RuntimeError("Primary migration backup readback differs")


async def ensure_daily_idle():
    redis = Redis.from_url(get_settings().redis_url)
    try:
        if await redis.zcard("arq:daily-valid-creators"):
            raise RuntimeError("Independent daily queue is not idle; keep schema unchanged")
    finally:
        await redis.aclose()


async def migrate():
    async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
        response = await http.get("http://127.0.0.1:18080/readyz")
    if response.status_code != 200:
        raise RuntimeError("API readiness gate failed")
    batch = _valid_creator_batch_date(datetime.now(UTC))
    if not await SampleBusinessReadiness._daily_sync_succeeded(batch):
        raise RuntimeError("Independent daily success receipt is not ready")
    await ensure_daily_idle()
    client = feishu_client()
    await verify_target_identity(client)
    header = {"Authorization": "Bearer " + await client.tenant_access_token()}
    endpoint = f"/open-apis/bitable/v1/apps/{BASE}/tables/{TABLE}/fields"

    async def schema():
        result = await client.request_json("GET", endpoint,
            retry_mode="idempotent", headers=header, params={"page_size": 100})
        if result["data"].get("has_more"):
            raise RuntimeError("Unexpected schema pagination")
        return result["data"]["items"]

    fields = await schema()
    by_name = {row["field_name"]: row for row in fields}
    primary, account = by_name.get("产品线"), by_name.get("账号名称")
    if not primary or not account or not primary.get("is_primary") or account.get("is_primary"):
        raise RuntimeError("Authorized primary-column identities differ")
    if primary["field_id"] != "fld51re6fs" or account["field_id"] != "fldMNQfggl":
        raise RuntimeError("Authorized field IDs differ")
    baseline = await target_rows(client)
    updates = account_copy(baseline)
    snapshot = Path("/opt/erp/backups/daily-valid-primary-cutover-20261014.json")
    await asyncio.to_thread(save_snapshot, snapshot, fields, baseline)
    expected = comparable_rows(baseline, {"产品线"})

    async def rename(field, name):
        await client.request_json("PUT", endpoint + "/" + field["field_id"],
            retry_mode="idempotent", headers=header,
            json={"field_name": name, "type": 1})

    async def verify_final(current_fields=None):
        final_fields = current_fields if current_fields is not None else await schema()
        by_id = {row["field_id"]: row for row in final_fields}
        final_primary = by_id.get(primary["field_id"], {})
        if (
            account["field_id"] in by_id
            or final_primary.get("field_name") != "账号名称"
            or not final_primary.get("is_primary")
            or {row["field_name"]: row["type"] for row in final_fields} != FIELD_TYPES
        ):
            raise RuntimeError("Final primary field identity requires audit")
        await verify_target_identity(client)
        after = await target_rows(client)
        if comparable_rows(after, set()) != expected:
            raise RuntimeError("Final account values or record IDs require audit")
        print(json.dumps({"status": "verified", "records": len(after),
            "product_line_removed": True, "account_values_unchanged": True,
            "record_ids_unchanged": True, "other_fields_unchanged": True}), flush=True)

    delete_attempted = False
    try:
        for offset in range(0, len(updates), 500):
            payload = updates[offset:offset + 500]
            result = await client.batch_records(BASE, TABLE, "batch_update", payload,
                retry_mode="idempotent")
            if {row["record_id"] for row in result.get("records", [])} != {
                row["record_id"] for row in payload}:
                raise RuntimeError("Primary account-copy response differs")
        copied = await target_rows(client)
        if comparable_rows(copied, {"产品线"}) != expected or any(
            row["fields"].get("产品线") != row["fields"].get("账号名称") for row in copied):
            raise RuntimeError("Primary account-copy readback differs")
        await rename(account, BACKUP_NAME)
        await rename(primary, "账号名称")
        renamed = await target_rows(client)
        if comparable_rows(renamed, {BACKUP_NAME}) != expected or any(
            row["fields"].get(BACKUP_NAME) != row["fields"].get("账号名称") for row in renamed):
            raise RuntimeError("Primary account-rename readback differs")
        actual = {row["field_name"]: row["type"] for row in await schema()}
        if actual != {**FIELD_TYPES, BACKUP_NAME: 1}:
            raise RuntimeError("Pre-delete field schema differs")
        latest = await target_rows(client)
        if comparable_rows(latest, {BACKUP_NAME}) != expected or any(
            row["fields"].get(BACKUP_NAME) != row["fields"].get("账号名称") for row in latest):
            raise RuntimeError("Target changed immediately before column removal")
        await ensure_daily_idle()
        delete_attempted = True
        await client.request_json("DELETE", endpoint + "/" + account["field_id"],
            retry_mode="idempotent", headers=header)
        await verify_final()
    except Exception:
        try:
            current_fields = await schema()
        except Exception as schema_error:
            raise RuntimeError("Primary cutover outcome unknown; schema audit required") from schema_error
        current = {row["field_id"]: row for row in current_fields}
        if delete_attempted and account["field_id"] not in current:
            # A lost DELETE response is not proof of failure. Never restore the
            # surviving primary account field to the obsolete product-line data.
            try:
                await verify_final(current_fields)
                return
            except Exception as audit_error:
                raise RuntimeError("Primary cutover requires readback audit after column removal") from audit_error
        if primary["field_id"] not in current or account["field_id"] not in current:
            raise RuntimeError("Primary migration field identity changed; audit required")
        if current[primary["field_id"]]["field_name"] != "产品线":
            await rename(primary, "产品线")
        if current[account["field_id"]]["field_name"] != "账号名称":
            await rename(account, "账号名称")
        restore = [{"record_id": row["record_id"],
            "fields": {"产品线": row["fields"].get("产品线")}} for row in baseline]
        for offset in range(0, len(restore), 500):
            await client.batch_records(BASE, TABLE, "batch_update", restore[offset:offset + 500],
                retry_mode="idempotent")
        if comparable_rows(await target_rows(client), set()) != comparable_rows(baseline, set()):
            raise RuntimeError("Primary migration rollback requires audit")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-authorized", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(migrate())
