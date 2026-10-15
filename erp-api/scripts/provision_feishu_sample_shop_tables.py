from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

import httpx

from erp_api.core.config import get_settings

API_BASE = "https://example.invalid/configure-resource"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-table-id", required=True)
    parser.add_argument("--table-name", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _data(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        raise RuntimeError(f"Feishu {operation} returned invalid JSON.") from None
    if not isinstance(payload, dict) or payload.get("code") != 0:
        code = payload.get("code") if isinstance(payload, dict) else "invalid"
        message = payload.get("msg") if isinstance(payload, dict) else None
        raise RuntimeError(
            f"Feishu {operation} failed with code {code}: {message}."
        )
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


async def _token(client: httpx.AsyncClient) -> str:
    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError("Feishu application credentials are not configured.")
    response = await client.post(
        "/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret.get_secret_value(),
        },
    )
    payload = response.json()
    token = payload.get("tenant_access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Unable to obtain Feishu tenant token.")
    return token


async def _list_items(
    client: httpx.AsyncClient,
    path: str,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, object] = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = _data(await client.get(path, headers=headers, params=params), "list")
        page = data.get("items")
        if not isinstance(page, list):
            raise TypeError("Feishu list response is incomplete.")
        items.extend(item for item in page if isinstance(item, dict))
        if data.get("has_more") is not True:
            return items
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token:
            raise RuntimeError("Feishu list pagination is incomplete.")


def _property(field: dict[str, Any]) -> dict[str, Any] | None:
    value = field.get("property")
    if not isinstance(value, dict):
        return None
    if field.get("type") == 3:
        options = value.get("options")
        if not isinstance(options, list):
            return None
        return {
            "options": [
                {"name": option["name"], "color": option.get("color", 0)}
                for option in options
                if isinstance(option, dict) and isinstance(option.get("name"), str)
            ]
        }
    allowed = {
        key: value[key]
        for key in ("formatter", "currency_code", "date_formatter", "auto_fill")
        if key in value
    }
    return allowed or None


def _field_body(field: dict[str, Any]) -> dict[str, Any]:
    name = field.get("field_name")
    field_type = field.get("type")
    if not isinstance(name, str) or not name or not isinstance(field_type, int):
        raise RuntimeError("Feishu source field is invalid.")
    body: dict[str, Any] = {"field_name": name, "type": field_type}
    if field_property := _property(field):
        body["property"] = field_property
    return body


def _table_body(
    name: str,
    source_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = next(
        (field for field in source_fields if field.get("is_primary") is True),
        None,
    )
    if not isinstance(primary, dict):
        raise TypeError("Feishu source table primary field is unavailable.")
    return {
        "table": {
            "name": name,
            "default_view_name": "最新申请",
            "fields": [_field_body(primary)],
        }
    }


def _created_table_id(data: dict[str, Any]) -> str | None:
    direct = data.get("table_id")
    if isinstance(direct, str) and direct:
        return direct
    table = data.get("table")
    nested = table.get("table_id") if isinstance(table, dict) else None
    return nested if isinstance(nested, str) and nested else None


async def _create_table(
    client: httpx.AsyncClient,
    table_path: str,
    headers: dict[str, str],
    name: str,
    source_fields: list[dict[str, Any]],
) -> str:
    data = _data(
        await client.post(
            table_path,
            headers=headers,
            json=_table_body(name, source_fields),
        ),
        f"create table {name}",
    )
    table_id = _created_table_id(data)
    if table_id is None:
        raise RuntimeError(f"Feishu did not return table ID for {name}.")
    return table_id


async def _ensure_fields(
    client: httpx.AsyncClient,
    base_path: str,
    headers: dict[str, str],
    source_fields: list[dict[str, Any]],
    table_id: str,
) -> None:
    path = f"{base_path}/tables/{table_id}/fields"
    target_fields = await _list_items(client, path, headers)
    primary = next(
        (field for field in target_fields if field.get("is_primary") is True),
        None,
    )
    source_primary = next(
        (field for field in source_fields if field.get("is_primary") is True),
        None,
    )
    if not isinstance(primary, dict) or not isinstance(source_primary, dict):
        raise TypeError("Feishu table primary field is unavailable.")
    primary_id = primary.get("field_id")
    if not isinstance(primary_id, str):
        raise TypeError("Feishu table primary field ID is invalid.")
    if (
        primary.get("field_name") != source_primary.get("field_name")
        or primary.get("type") != source_primary.get("type")
    ):
        _data(
            await client.put(
                f"{path}/{primary_id}",
                headers=headers,
                json=_field_body(source_primary),
            ),
            "update primary field",
        )
    target_by_name = {
        field.get("field_name"): field
        for field in target_fields
        if isinstance(field.get("field_name"), str)
    }
    for field in source_fields:
        if field.get("is_primary") is True:
            continue
        existing = target_by_name.get(field.get("field_name"))
        if existing is not None:
            if existing.get("type") != field.get("type"):
                raise RuntimeError("Feishu target field type does not match source.")
            continue
        _data(
            await client.post(path, headers=headers, json=_field_body(field)),
            f"create field {field.get('field_name')}",
        )


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.feishu_sample_base_token:
        raise RuntimeError("Feishu sample Base is not configured.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    base_path = f"/open-apis/bitable/v1/apps/{base_token}"
    table_path = f"{base_path}/tables"
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}"}
        tables = await _list_items(client, table_path, headers)
        by_name = {
            item.get("name"): item.get("table_id")
            for item in tables
            if isinstance(item.get("name"), str)
            and isinstance(item.get("table_id"), str)
        }
        source_fields = await _list_items(
            client,
            f"{table_path}/{arguments.source_table_id}/fields",
            headers,
        )
        actions = [name for name in arguments.table_name if name not in by_name]
        created: dict[str, str] = {}
        if arguments.apply:
            for name in actions:
                table_id = await _create_table(
                    client,
                    table_path,
                    headers,
                    name,
                    source_fields,
                )
                created[name] = table_id
                by_name[name] = table_id
            for name in arguments.table_name:
                await _ensure_fields(
                    client,
                    base_path,
                    headers,
                    source_fields,
                    by_name[name],
                )
        print(
            json.dumps(
                {
                    "apply": arguments.apply,
                    "source_table_id": arguments.source_table_id,
                    "field_count": len(source_fields),
                    "to_create": actions,
                    "created": created,
                    "existing": {
                        name: by_name[name]
                        for name in arguments.table_name
                        if name in by_name
                    },
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
