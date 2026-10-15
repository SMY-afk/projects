from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from erp_api.core.config import get_settings
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_SOURCE_RECORD_FIELD,
    AI_INVITATION_TIME_FIELD,
)
from scripts.provision_feishu_sample_shop_tables import (
    API_BASE,
    _created_table_id,
    _data,
    _list_items,
    _token,
)

TABLE_NAME = "AI邀约表（镜像）"
VIEW_NAME = "全部邀约记录"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _table_body() -> dict[str, object]:
    return {
        "table": {
            "name": TABLE_NAME,
            "default_view_name": VIEW_NAME,
            "fields": [{"field_name": AI_INVITATION_CREATOR_FIELD, "type": 1}],
        }
    }


def _field_map(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        field["field_name"]: field
        for field in fields
        if isinstance(field.get("field_name"), str)
    }


async def _ensure_fields(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
) -> None:
    fields = await _list_items(client, path, headers)
    by_name = _field_map(fields)
    primary = next((field for field in fields if field.get("is_primary") is True), None)
    if not isinstance(primary, dict) or not isinstance(primary.get("field_id"), str):
        raise TypeError("AI invitation mirror primary field is unavailable.")
    if primary.get("field_name") != AI_INVITATION_CREATOR_FIELD:
        _data(
            await client.put(
                f"{path}/{primary['field_id']}",
                headers=headers,
                json={"field_name": AI_INVITATION_CREATOR_FIELD, "type": 1},
            ),
            "update AI invitation mirror primary field",
        )
    definitions = (
        {
            "field_name": AI_INVITATION_TIME_FIELD,
            "type": 5,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"},
        },
        {"field_name": AI_INVITATION_SOURCE_RECORD_FIELD, "type": 1},
    )
    for definition in definitions:
        existing = by_name.get(definition["field_name"])
        if existing is None:
            _data(
                await client.post(path, headers=headers, json=definition),
                f"create mirror field {definition['field_name']}",
            )
        elif existing.get("type") != definition["type"]:
            raise RuntimeError(
                f"AI invitation mirror field type is invalid: {definition['field_name']}."
            )


def _verify(fields: list[dict[str, Any]]) -> None:
    by_name = _field_map(fields)
    expected = {
        AI_INVITATION_CREATOR_FIELD: 1,
        AI_INVITATION_TIME_FIELD: 5,
        AI_INVITATION_SOURCE_RECORD_FIELD: 1,
    }
    invalid = {
        name: None if by_name.get(name) is None else by_name[name].get("type")
        for name, field_type in expected.items()
        if by_name.get(name) is None or by_name[name].get("type") != field_type
    }
    if invalid:
        raise RuntimeError(f"AI invitation mirror fields were not verified: {invalid}.")
    if by_name[AI_INVITATION_CREATOR_FIELD].get("is_primary") is not True:
        raise RuntimeError("AI invitation mirror creator field is not primary.")


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.feishu_sample_base_token:
        raise RuntimeError("Feishu sample Base is not configured.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    table_path = f"/open-apis/bitable/v1/apps/{base_token}/tables"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}"}
        tables = await _list_items(client, table_path, headers)
        matches = [table for table in tables if table.get("name") == TABLE_NAME]
        if len(matches) > 1:
            raise RuntimeError("AI invitation mirror table name is duplicated.")
        table_id = matches[0].get("table_id") if matches else None
        if not arguments.apply:
            print(
                json.dumps(
                    {
                        "apply": False,
                        "table_id": table_id,
                        "actions": [] if table_id else [f"create-table:{TABLE_NAME}"],
                    },
                    ensure_ascii=True,
                )
            )
            return
        if not isinstance(table_id, str) or not table_id:
            data = _data(
                await client.post(table_path, headers=headers, json=_table_body()),
                "create AI invitation mirror table",
            )
            table_id = _created_table_id(data)
        if not table_id:
            raise RuntimeError("Feishu did not return AI invitation mirror table ID.")
        field_path = f"{table_path}/{table_id}/fields"
        await _ensure_fields(client, field_path, headers)
        fields = await _list_items(client, field_path, headers)
        _verify(fields)
        record_data = _data(
            await client.get(
                f"{table_path}/{table_id}/records",
                headers=headers,
                params={"page_size": 1},
            ),
            "read AI invitation mirror table",
        )
        print(
            json.dumps(
                {
                    "apply": True,
                    "table_id": table_id,
                    "table_name": TABLE_NAME,
                    "record_count": record_data.get("total"),
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
