"""Rename the local-shop display token in the daily valid creator table."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

from scripts.daily_valid_creator_io import (
    BASE,
    TABLE,
    feishu_client,
    target_rows,
    verify_target_identity,
)

OLD_LABEL = "本土店"
NEW_LABEL = "本土2店"
FIELD = "匹配店铺"
CHUNK_SIZE = 500


def renamed_value(value: object) -> str:
    tokens = [item.strip() for item in str(value or "").replace(",", "；").split("；")]
    result: list[str] = []
    for token in tokens:
        if not token:
            continue
        renamed = NEW_LABEL if token == OLD_LABEL else token
        if renamed not in result:
            result.append(renamed)
    return "；".join(result)


def plan(rows: list[dict]) -> dict:
    updates = []
    for row in rows:
        fields = row.get("fields") or {}
        before = str(fields.get(FIELD) or "")
        after = renamed_value(before)
        if before != after:
            updates.append(
                {"record_id": row["record_id"], "before": before, "after": after}
            )
    updates.sort(key=lambda item: item["record_id"])
    digest = hashlib.sha256(
        json.dumps(updates, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {"updates": updates, "count": len(updates), "hash": digest}


def chunks(items: list[dict]) -> list[list[dict]]:
    return [items[index : index + CHUNK_SIZE] for index in range(0, len(items), CHUNK_SIZE)]


def fields_by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["record_id"]: row.get("fields") or {} for row in rows}


async def apply_plan(client, baseline: list[dict], expected: dict) -> None:
    current = await target_rows(client)
    if plan(current)["hash"] != expected["hash"] or fields_by_id(current) != fields_by_id(
        baseline
    ):
        raise RuntimeError("Target changed after preview; no write was made")
    try:
        for batch in chunks(expected["updates"]):
            payload = [
                {"record_id": item["record_id"], "fields": {FIELD: item["after"]}}
                for item in batch
            ]
            result = await client.batch_records(
                BASE, TABLE, "batch_update", payload, retry_mode="idempotent"
            )
            returned = {item.get("record_id") for item in result.get("records", [])}
            if returned != {item["record_id"] for item in batch}:
                raise RuntimeError("Feishu update response IDs mismatch")
        after = await target_rows(client)
        if plan(after)["count"] != 0 or len(after) != len(baseline):
            raise RuntimeError("Post-write preview is not zero-difference")
        before_by_id = fields_by_id(baseline)
        after_by_id = fields_by_id(after)
        if set(before_by_id) != set(after_by_id):
            raise RuntimeError("Post-write record identity changed")
        changed_ids = {item["record_id"] for item in expected["updates"]}
        for record_id, before_fields in before_by_id.items():
            actual = after_by_id[record_id]
            expected_fields = dict(before_fields)
            if record_id in changed_ids:
                expected_fields[FIELD] = renamed_value(before_fields.get(FIELD))
            if actual != expected_fields:
                raise RuntimeError("Post-write non-target field changed")
    except Exception as error:
        for batch in chunks(expected["updates"]):
            payload = [
                {"record_id": item["record_id"], "fields": {FIELD: item["before"]}}
                for item in batch
            ]
            await client.batch_records(
                BASE, TABLE, "batch_update", payload, retry_mode="idempotent"
            )
        restored = await target_rows(client)
        if fields_by_id(restored) != fields_by_id(baseline):
            raise RuntimeError("Apply failed and rollback is incomplete") from error
        raise RuntimeError("Apply failed; target field was restored") from error


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-hash")
    args = parser.parse_args()
    client = feishu_client()
    await verify_target_identity(client)
    baseline = await target_rows(client)
    preview = plan(baseline)
    result = {
        "mode": "apply" if args.apply_hash else "preview",
        "base_verified": True,
        "table_verified": True,
        "total": len(baseline),
        "updates": preview["count"],
        "hash": preview["hash"],
    }
    if args.apply_hash:
        if args.apply_hash != preview["hash"]:
            raise RuntimeError("Preview hash changed; no write was made")
        await apply_plan(client, baseline, preview)
        result["status"] = "verified"
        result["second_preview"] = [0, 0, 0]
    print(json.dumps(result, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
