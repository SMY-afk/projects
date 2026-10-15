from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from uuid import UUID

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient

FIELD_NAME = "商品ID"
TEXT_FIELD_TYPE = 1
MULTI_SELECT_FIELD_TYPE = 4
MULTI_SELECT_UI_TYPE = "MultiSelect"


@dataclass(frozen=True)
class TableTarget:
    label: str
    table_id: str


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _targets(settings) -> tuple[TableTarget, ...]:
    labels = {
        UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6"): "cross-border-3",
        UUID("50770999-40ce-5b84-bb01-13701932bdf1"): "cross-border-4",
        UUID("fe629cb8-fa7b-56a5-970c-2f6e9ebc5703"): "cross-border-7",
        UUID("5e1fed24-8268-5b5a-9ead-5efb862e7a51"): "cross-border-12",
    }
    result = []
    seen = set()
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


def _choices(value: object) -> tuple[str, ...]:
    raw_values = value if isinstance(value, list) else [value]
    result = []
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        for item in raw.split("、"):
            cleaned = item.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return tuple(result)


async def _inspect(settings, target: TableTarget):
    client = _client(settings, target.table_id)
    fields, records = await asyncio.gather(
        client.list_field_metadata(),
        client.list_record_snapshots(),
    )
    field = fields.get(FIELD_NAME)
    if field is None:
        raise RuntimeError(f"{target.label} is missing {FIELD_NAME}.")
    if field.field_type not in {TEXT_FIELD_TYPE, MULTI_SELECT_FIELD_TYPE}:
        raise RuntimeError(f"{target.label} has an unsupported {FIELD_NAME} type.")
    options = []
    multi_rows = []
    for record in records:
        value = record.snapshot.fields.get(FIELD_NAME)
        choices = _choices(value)
        for choice in choices:
            if choice not in options:
                options.append(choice)
        if len(choices) > 1:
            multi_rows.append((record.record_id, choices))
    return client, field, records, tuple(options), tuple(multi_rows)


def _option_property(options: tuple[str, ...]) -> dict[str, object]:
    return {
        "options": [
            {"name": name, "color": index % 55}
            for index, name in enumerate(options)
        ]
    }


async def _apply_target(settings, target: TableTarget, inspection) -> dict[str, object]:
    client, field, _records, options, multi_rows = inspection
    if field.field_type == TEXT_FIELD_TYPE:
        await client.update_field_definition(
            field.field_id,
            field_name=FIELD_NAME,
            field_type=MULTI_SELECT_FIELD_TYPE,
            ui_type=MULTI_SELECT_UI_TYPE,
            field_property=_option_property(options),
        )
    updated = 0
    for offset in range(0, len(multi_rows), 500):
        batch = [
            (record_id, {FIELD_NAME: list(choices)})
            for record_id, choices in multi_rows[offset : offset + 500]
        ]
        if batch:
            updated += len(await client.batch_update_records(batch))
    verified_fields = await client.list_field_metadata()
    verified = verified_fields.get(FIELD_NAME)
    if verified is None or verified.field_type != MULTI_SELECT_FIELD_TYPE:
        raise RuntimeError(f"{target.label} {FIELD_NAME} migration was not verified.")
    if multi_rows:
        snapshots = {
            record.record_id: record.snapshot.fields.get(FIELD_NAME)
            for record in await client.list_record_snapshots()
        }
        for record_id, choices in multi_rows:
            if _choices(snapshots.get(record_id)) != choices:
                raise RuntimeError(
                    f"{target.label} multi-product value migration was not verified."
                )
    return {
        "label": target.label,
        "field_type": verified.field_type,
        "options": len(options),
        "multi_rows_updated": updated,
    }


async def main(apply_changes: bool) -> None:
    settings = get_settings()
    targets = _targets(settings)
    inspections = await asyncio.gather(
        *(_inspect(settings, target) for target in targets)
    )
    report = [
        {
            "label": target.label,
            "field_type": inspection[1].field_type,
            "records": len(inspection[2]),
            "options": len(inspection[3]),
            "multi_product_rows": len(inspection[4]),
        }
        for target, inspection in zip(targets, inspections, strict=True)
    ]
    print(json.dumps({"apply": apply_changes, "tables": report}, ensure_ascii=False))
    if not apply_changes:
        return
    results = []
    for target, inspection in zip(targets, inspections, strict=True):
        results.append(await _apply_target(settings, target, inspection))
    print(json.dumps({"updated": results}, ensure_ascii=False))


if __name__ == "__main__":
    args = _arguments()
    asyncio.run(main(args.apply))
