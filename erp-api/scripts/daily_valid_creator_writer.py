"""Small Feishu batch writer with best-effort rollback of this run's changes."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable

from erp_api.services.feishu_client import FeishuClient
from scripts.daily_valid_creator_shop_rows import shop_record_key
from scripts.daily_valid_creator_io import BASE, TABLE

CHUNK_SIZE = 500


def chunks(items: list) -> list[list]:
    return [items[i : i + CHUNK_SIZE] for i in range(0, len(items), CHUNK_SIZE)]


async def write_operations(
    client: FeishuClient,
    operations: dict,
    baseline: list[dict],
    today_millis: int,
    reread: Callable[[FeishuClient], Awaitable[list[dict]]],
    verify: Callable[[], Awaitable[None]],
) -> None:
    baseline_by_id = {row["record_id"]: row for row in baseline}
    try:
        for batch in chunks(operations["update"]):
            payload = [
                {
                    "record_id": record_id,
                    "fields": {**fields, "最新更新时间": today_millis},
                }
                for record_id, fields in batch
            ]
            data = await client.batch_records(
                BASE, TABLE, "batch_update", payload, retry_mode="idempotent"
            )
            response_records = data.get("records")
            if not isinstance(response_records, list) or len(response_records) != len(
                payload
            ):
                raise RuntimeError("Feishu update response count mismatch")
            returned = {item.get("record_id") for item in response_records}
            expected = {item["record_id"] for item in payload}
            if returned != expected:
                raise RuntimeError("Feishu update response did not match requested IDs")
        for batch in chunks(operations["create"]):
            payload = [
                {
                    "fields": {
                        **{
                            key: value
                            for key, value in fields.items()
                            if value is not None
                        },
                        "最新更新时间": today_millis,
                    }
                }
                for fields in batch
            ]
            data = await client.batch_records(
                BASE, TABLE, "batch_create", payload, retry_mode="rate_limit"
            )
            records = data.get("records")
            if not isinstance(records, list) or len(records) != len(payload):
                raise RuntimeError("Feishu create response count mismatch")
            ids = [item.get("record_id") for item in records]
            if len(set(ids)) != len(ids) or any(
                not isinstance(record_id, str) or not record_id for record_id in ids
            ):
                raise RuntimeError("Feishu create response ID missing")
        for batch in chunks(operations["delete"]):
            data = await client.batch_records(
                BASE, TABLE, "batch_delete", batch, retry_mode="idempotent"
            )
            returned = {item.get("record_id") for item in data.get("records", [])}
            if returned != set(batch):
                raise RuntimeError("Feishu delete response did not match requested IDs")
        await verify()
    except Exception as error:
        try:
            current = await reread(client)
            current_by_id = {row["record_id"]: row for row in current}
            restore = []
            for record_id, changed_fields in operations["update"]:
                if record_id not in current_by_id:
                    raise RuntimeError("Updated record vanished before rollback")
                original = baseline_by_id[record_id]["fields"]
                fields = {
                    name: original.get(name)
                    for name in (*changed_fields, "最新更新时间")
                }
                restore.append({"record_id": record_id, "fields": fields})
            for batch in chunks(restore):
                await client.batch_records(
                    BASE, TABLE, "batch_update", batch, retry_mode="idempotent"
                )
            created_keys = {
                shop_record_key(fields)
                for fields in operations["create"]
            }
            new_ids = []
            for record_id, row in current_by_id.items():
                if record_id in baseline_by_id:
                    continue
                fields = row.get("fields") or {}
                key = shop_record_key(fields)
                if key in created_keys and str(fields.get("最新更新时间")) == str(
                    today_millis
                ):
                    new_ids.append(record_id)
            for batch in chunks(new_ids):
                await client.batch_records(
                    BASE, TABLE, "batch_delete", batch, retry_mode="idempotent"
                )
            missing_deleted = [
                baseline_by_id[record_id]
                for record_id in operations["delete"]
                if record_id not in current_by_id
            ]
            for batch in chunks(missing_deleted):
                await client.batch_records(
                    BASE,
                    TABLE,
                    "batch_create",
                    [{"fields": row["fields"]} for row in batch],
                    retry_mode="rate_limit",
                )
            after = await reread(client)
            original_values = Counter(
                json.dumps(
                    row["fields"], ensure_ascii=False, sort_keys=True, default=str
                )
                for row in baseline
            )
            restored_values = Counter(
                json.dumps(
                    row["fields"], ensure_ascii=False, sort_keys=True, default=str
                )
                for row in after
            )
            if original_values != restored_values:
                raise RuntimeError("Rollback target values mismatch")
        except Exception as rollback_error:
            raise RuntimeError(
                "Feishu apply failed and rollback is incomplete"
            ) from rollback_error
        if missing_deleted:
            raise RuntimeError(
                "Feishu apply failed; values restored but deleted record IDs changed"
            ) from error
        raise RuntimeError(
            "Feishu apply failed; rollback restored target records"
        ) from error
