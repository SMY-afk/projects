from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import (
    FEISHU_BATCH_RECORD_LIMIT,
    FeishuSampleBatchClient,
)

FIELD_NAME = "首次同步时间"


@dataclass(frozen=True)
class TableTarget:
    label: str
    table_id: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--label",
        action="append",
        help="Only process the exact table label; repeat to select multiple tables.",
    )
    return parser.parse_args()


def _targets(settings) -> tuple[TableTarget, ...]:
    labels = {
        UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6"): "cross-border-3",
        UUID("50770999-40ce-5b84-bb01-13701932bdf1"): "cross-border-4",
        UUID("fe629cb8-fa7b-56a5-970c-2f6e9ebc5703"): "cross-border-7",
        UUID("5e1fed24-8268-5b5a-9ead-5efb862e7a51"): "cross-border-12",
    }
    result: list[TableTarget] = []
    seen: set[str] = set()
    if settings.feishu_sample_table_id:
        result.append(TableTarget("local", settings.feishu_sample_table_id))
        seen.add(settings.feishu_sample_table_id)
    for shop_id, table_id in settings.feishu_sample_shop_table_ids.items():
        if table_id in seen:
            continue
        result.append(TableTarget(labels.get(shop_id, str(shop_id)), table_id))
        seen.add(table_id)
    return tuple(result)


def _client(settings, table_id: str) -> FeishuSampleBatchClient:
    return FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=table_id,
    )


async def _raw_records(client: FeishuSampleBatchClient) -> tuple[dict[str, Any], ...]:
    token = await client.tenant_access_token()
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    expected_total: int | None = None
    while True:
        params: dict[str, object] = {
            "page_size": FEISHU_BATCH_RECORD_LIMIT,
            "automatic_fields": True,
        }
        if page_token:
            params["page_token"] = page_token
        data = await client._request(
            "GET", client._record_path(), token=token, params=params
        )
        total = data.get("total")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise RuntimeError("Feishu record total is invalid.")
        if expected_total is not None and total != expected_total:
            raise RuntimeError("Feishu record total changed during backfill.")
        expected_total = total
        items = data.get("items") or []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise RuntimeError("Feishu record page is invalid.")
        records.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token:
            raise RuntimeError("Feishu record pagination is incomplete.")
    if len(records) != expected_total:
        raise RuntimeError("Feishu record listing is incomplete.")
    return tuple(records)


def _updates(records: tuple[dict[str, Any], ...]) -> list[tuple[str, dict[str, int]]]:
    updates = []
    for item in records:
        record_id = item.get("record_id")
        created_time = item.get("created_time")
        fields = item.get("fields")
        if (
            not isinstance(record_id, str)
            or not record_id
            or isinstance(created_time, bool)
            or not isinstance(created_time, int)
            or created_time <= 0
            or not isinstance(fields, dict)
        ):
            raise RuntimeError("Feishu record creation metadata is invalid.")
        if fields.get(FIELD_NAME) != created_time:
            updates.append((record_id, {FIELD_NAME: created_time}))
    return updates


def _chunks(items: list, size: int = FEISHU_BATCH_RECORD_LIMIT):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


async def _run_target(settings, target: TableTarget, *, apply: bool) -> dict[str, object]:
    client = _client(settings, target.table_id)
    records = await _raw_records(client)
    updates = _updates(records)
    if apply:
        for batch in _chunks(updates):
            await client.batch_update_records(batch)
        remaining = _updates(await _raw_records(client))
        if remaining:
            raise RuntimeError(
                f"{target.label} first-sync verification failed: {len(remaining)} rows."
            )
    return {
        "label": target.label,
        "table_id": target.table_id,
        "record_count": len(records),
        "update_count": len(updates),
        "applied": apply,
    }


async def _main() -> None:
    args = _arguments()
    settings = get_settings()
    targets = _targets(settings)
    if args.label:
        requested = set(args.label)
        targets = tuple(target for target in targets if target.label in requested)
        missing = requested.difference(target.label for target in targets)
        if missing:
            raise RuntimeError(
                f"Unknown table labels: {', '.join(sorted(missing))}."
            )
    results = []
    for target in targets:
        results.append(await _run_target(settings, target, apply=args.apply))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
