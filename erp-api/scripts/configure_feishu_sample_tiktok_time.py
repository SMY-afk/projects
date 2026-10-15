from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_client import FeishuSampleClient

FIELD_NAME = "TikTok申请时间"
FIELD_TYPE = 5
FIELD_UI_TYPE = "DateTime"
FIELD_PROPERTY = {"date_formatter": "yyyy/MM/dd HH:mm"}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def main(*, apply: bool) -> None:
    settings = get_settings()
    required = (
        settings.feishu_app_id,
        settings.feishu_app_secret,
        settings.feishu_sample_base_token,
    )
    if not all(required):
        raise RuntimeError("Feishu sample table configuration is incomplete.")
    table_ids = set(settings.feishu_sample_shop_table_ids.values())
    if settings.feishu_sample_table_id:
        table_ids.add(settings.feishu_sample_table_id)
    if not table_ids:
        raise RuntimeError("No Feishu sample tables are configured.")

    results: list[dict[str, str]] = []
    for table_id in sorted(table_ids):
        client = FeishuSampleClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=table_id,
        )
        fields = await client.list_field_metadata()
        existing = fields.get(FIELD_NAME)
        if existing is None:
            action = "would_create"
            if apply:
                existing = await client.create_field_definition(
                    field_name=FIELD_NAME,
                    field_type=FIELD_TYPE,
                    ui_type=FIELD_UI_TYPE,
                    field_property=FIELD_PROPERTY,
                )
                action = "created"
        else:
            action = "exists"
        if existing is not None and existing.field_type != FIELD_TYPE:
            raise RuntimeError(f"Feishu field type mismatch in table {table_id}.")
        results.append({"table_id": table_id, "action": action})

    print(json.dumps({"field": FIELD_NAME, "tables": results}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(apply=_arguments().apply))
