from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from erp_api.core.config import get_settings
from erp_api.services.sample_bd_invitation_protection import (
    BD_INVITATION_CREATOR_FIELD,
    BD_INVITATION_OWNER_FIELD,
)
from scripts.provision_feishu_sample_shop_tables import (
    API_BASE,
    _created_table_id,
    _data,
    _list_items,
    _token,
)

TABLE_NAME = "BD自主邀约保护名单"
VIEW_NAME = "当前7天保护"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _table_body() -> dict[str, object]:
    return {
        "table": {
            "name": TABLE_NAME,
            "default_view_name": VIEW_NAME,
            "fields": [{"field_name": BD_INVITATION_CREATOR_FIELD, "type": 1}],
        }
    }


def _owner_field_body(bd_names: tuple[str, ...]) -> dict[str, object]:
    if not bd_names:
        raise RuntimeError("BD invitation protection requires configured BD names.")
    return {
        "field_name": BD_INVITATION_OWNER_FIELD,
        "type": 3,
        "property": {
            "options": [
                {"name": name, "color": index % 8}
                for index, name in enumerate(bd_names)
            ]
        },
    }


def _field_names(fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        field["field_name"]: field
        for field in fields
        if isinstance(field.get("field_name"), str)
    }


async def _ensure_fields(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
    bd_names: tuple[str, ...],
) -> None:
    fields = await _list_items(client, path, headers)
    by_name = _field_names(fields)
    primary = next((field for field in fields if field.get("is_primary") is True), None)
    if not isinstance(primary, dict) or not isinstance(primary.get("field_id"), str):
        raise TypeError("BD invitation protection primary field is unavailable.")
    if primary.get("field_name") != BD_INVITATION_CREATOR_FIELD:
        _data(
            await client.put(
                f"{path}/{primary['field_id']}",
                headers=headers,
                json={"field_name": BD_INVITATION_CREATOR_FIELD, "type": 1},
            ),
            "update invitation protection primary field",
        )
    owner = by_name.get(BD_INVITATION_OWNER_FIELD)
    if owner is None:
        _data(
            await client.post(
                path,
                headers=headers,
                json=_owner_field_body(bd_names),
            ),
            "create invitation protection BD field",
        )
    elif owner.get("type") != 3:
        raise RuntimeError(
            "BD invitation protection owner field must be single select."
        )


def _verify_fields(fields: list[dict[str, Any]], bd_names: tuple[str, ...]) -> None:
    by_name = _field_names(fields)
    creator = by_name.get(BD_INVITATION_CREATOR_FIELD)
    owner = by_name.get(BD_INVITATION_OWNER_FIELD)
    if (
        creator is None
        or creator.get("type") != 1
        or creator.get("is_primary") is not True
    ):
        raise RuntimeError("BD invitation protection creator field was not verified.")
    if owner is None or owner.get("type") != 3:
        raise RuntimeError("BD invitation protection owner field was not verified.")
    options = owner.get("property", {}).get("options", [])
    option_names = {
        option.get("name") for option in options if isinstance(option, dict)
    }
    missing = sorted(set(bd_names) - option_names)
    if missing:
        raise RuntimeError(
            f"BD invitation protection owner options are incomplete: {missing}."
        )


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.feishu_sample_base_token:
        raise RuntimeError("Feishu sample Base is not configured.")
    bd_names = settings.sample_auto_assignment_bd_names
    base_token = settings.feishu_sample_base_token.get_secret_value()
    base_path = f"/open-apis/bitable/v1/apps/{base_token}"
    table_path = f"{base_path}/tables"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}"}
        tables = await _list_items(client, table_path, headers)
        matches = [table for table in tables if table.get("name") == TABLE_NAME]
        if len(matches) > 1:
            raise RuntimeError("BD invitation protection table name is duplicated.")
        table_id = matches[0].get("table_id") if matches else None
        actions = [] if table_id else [f"create-table:{TABLE_NAME}"]
        if not arguments.apply:
            print(
                json.dumps(
                    {"apply": False, "table_id": table_id, "actions": actions},
                    ensure_ascii=True,
                )
            )
            return
        if not isinstance(table_id, str) or not table_id:
            data = _data(
                await client.post(table_path, headers=headers, json=_table_body()),
                "create BD invitation protection table",
            )
            table_id = _created_table_id(data)
        if not table_id:
            raise RuntimeError("Feishu did not return invitation protection table ID.")
        field_path = f"{table_path}/{table_id}/fields"
        await _ensure_fields(client, field_path, headers, bd_names)
        fields = await _list_items(client, field_path, headers)
        _verify_fields(fields, bd_names)
        record_data = _data(
            await client.get(
                f"{table_path}/{table_id}/records",
                headers=headers,
                params={"page_size": 1, "automatic_fields": True},
            ),
            "read BD invitation protection table",
        )
        print(
            json.dumps(
                {
                    "apply": True,
                    "table_id": table_id,
                    "table_name": TABLE_NAME,
                    "fields": [BD_INVITATION_CREATOR_FIELD, BD_INVITATION_OWNER_FIELD],
                    "record_count": record_data.get("total"),
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
