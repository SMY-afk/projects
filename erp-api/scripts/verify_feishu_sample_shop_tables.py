from __future__ import annotations

import argparse
import asyncio
import json

import httpx

from erp_api.core.config import get_settings
from scripts.provision_feishu_sample_shop_tables import API_BASE, _data, _list_items, _token


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-name", action="append", required=True)
    parser.add_argument("--required-field", action="append", default=[])
    return parser.parse_args()


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.feishu_sample_base_token:
        raise RuntimeError("Feishu sample Base is not configured.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    base_path = f"/open-apis/bitable/v1/apps/{base_token}"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}"}
        tables = await _list_items(client, f"{base_path}/tables", headers)
        by_name = {
            table.get("name"): table.get("table_id")
            for table in tables
            if isinstance(table.get("name"), str)
            and isinstance(table.get("table_id"), str)
        }
        verified: dict[str, object] = {}
        for name in arguments.table_name:
            table_id = by_name.get(name)
            if table_id is None:
                raise RuntimeError(f"Feishu table is missing: {name}.")
            fields = await _list_items(
                client, f"{base_path}/tables/{table_id}/fields", headers
            )
            field_names = {
                field.get("field_name")
                for field in fields
                if isinstance(field.get("field_name"), str)
            }
            missing = sorted(set(arguments.required_field) - field_names)
            if missing:
                raise RuntimeError(
                    f"Feishu table {name} is missing required fields: {missing}."
                )
            views = await _list_items(
                client, f"{base_path}/tables/{table_id}/views", headers
            )
            record_data = _data(
                await client.get(
                    f"{base_path}/tables/{table_id}/records",
                    headers=headers,
                    params={"page_size": 1},
                ),
                "list records",
            )
            verified[name] = {
                "table_id": table_id,
                "field_count": len(fields),
                "record_count": record_data.get("total"),
                "views": [
                    {"view_id": view.get("view_id"), "view_name": view.get("view_name")}
                    for view in views
                ],
            }
    print(json.dumps(verified, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
