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
    BD_INVITATION_REMARK_FIELD,
)
from scripts.provision_feishu_sample_shop_tables import (
    API_BASE,
    _data,
    _list_items,
    _token,
)

DEFAULT_CREATOR_FIELD = "文本"
DEFAULT_OWNER_FIELD = "单选"
SUBMITTED_AT_FIELD = "提交时间"
SUBMITTER_FIELD = "提交人"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _field_by_name(fields: list[dict[str, Any]], *names: str) -> dict[str, Any] | None:
    matches = [field for field in fields if field.get("field_name") in names]
    if len(matches) > 1:
        raise RuntimeError(f"Collection field names are ambiguous: {names}.")
    return matches[0] if matches else None


def _field_id(field: dict[str, Any], label: str) -> str:
    value = field.get("field_id")
    if not isinstance(value, str) or not value:
        raise TypeError(f"Collection {label} field ID is unavailable.")
    return value


def _owner_field_body(bd_names: tuple[str, ...]) -> dict[str, object]:
    if not bd_names:
        raise RuntimeError("BD invitation collection requires configured BD names.")
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


def _planned_actions(
    fields: list[dict[str, Any]], bd_names: tuple[str, ...]
) -> list[str]:
    creator = _field_by_name(fields, BD_INVITATION_CREATOR_FIELD, DEFAULT_CREATOR_FIELD)
    owner = _field_by_name(fields, BD_INVITATION_OWNER_FIELD, DEFAULT_OWNER_FIELD)
    if creator is None or creator.get("type") != 1:
        raise RuntimeError("Collection text question is unavailable or has wrong type.")
    if owner is None or owner.get("type") != 3:
        raise RuntimeError(
            "Collection single-select question is unavailable or has wrong type."
        )
    names = {field.get("field_name") for field in fields}
    if SUBMITTED_AT_FIELD not in names or SUBMITTER_FIELD not in names:
        raise RuntimeError("Collection automatic submission fields are incomplete.")
    actions: list[str] = []
    if creator.get("field_name") != BD_INVITATION_CREATOR_FIELD:
        actions.append(f"rename:{DEFAULT_CREATOR_FIELD}->{BD_INVITATION_CREATOR_FIELD}")
    current_options = {
        option.get("name")
        for option in owner.get("property", {}).get("options", [])
        if isinstance(option, dict)
    }
    if owner.get("field_name") != BD_INVITATION_OWNER_FIELD:
        actions.append(f"rename:{DEFAULT_OWNER_FIELD}->{BD_INVITATION_OWNER_FIELD}")
    if current_options != set(bd_names):
        actions.append("replace-bd-options")
    remark = _field_by_name(fields, BD_INVITATION_REMARK_FIELD)
    if remark is None:
        actions.append(f"create:{BD_INVITATION_REMARK_FIELD}")
    elif remark.get("type") != 1:
        raise RuntimeError("Collection remark field must be text.")
    return actions


def _verify_fields(fields: list[dict[str, Any]], bd_names: tuple[str, ...]) -> None:
    creator = _field_by_name(fields, BD_INVITATION_CREATOR_FIELD)
    owner = _field_by_name(fields, BD_INVITATION_OWNER_FIELD)
    remark = _field_by_name(fields, BD_INVITATION_REMARK_FIELD)
    if creator is None or creator.get("type") != 1:
        raise RuntimeError("Collection creator ID question was not verified.")
    if owner is None or owner.get("type") != 3:
        raise RuntimeError("Collection BD owner question was not verified.")
    if remark is None or remark.get("type") != 1:
        raise RuntimeError("Collection remark field was not verified.")
    options = owner.get("property", {}).get("options", [])
    option_names = {
        option.get("name") for option in options if isinstance(option, dict)
    }
    if option_names != set(bd_names):
        raise RuntimeError("Collection BD owner options were not verified.")


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.feishu_sample_base_token:
        raise RuntimeError("Feishu sample Base is not configured.")
    bd_names = settings.sample_auto_assignment_bd_names
    base_token = settings.feishu_sample_base_token.get_secret_value()
    field_path = (
        f"/open-apis/bitable/v1/apps/{base_token}/tables/{arguments.table_id}/fields"
    )
    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as client:
        headers = {"Authorization": f"Bearer {await _token(client)}"}
        fields = await _list_items(client, field_path, headers)
        actions = _planned_actions(fields, bd_names)
        if not arguments.apply:
            print(
                json.dumps(
                    {
                        "apply": False,
                        "table_id": arguments.table_id,
                        "actions": actions,
                    },
                    ensure_ascii=True,
                )
            )
            return
        creator = _field_by_name(
            fields, BD_INVITATION_CREATOR_FIELD, DEFAULT_CREATOR_FIELD
        )
        owner = _field_by_name(fields, BD_INVITATION_OWNER_FIELD, DEFAULT_OWNER_FIELD)
        assert creator is not None and owner is not None
        if creator.get("field_name") != BD_INVITATION_CREATOR_FIELD:
            _data(
                await client.put(
                    f"{field_path}/{_field_id(creator, 'creator')}",
                    headers=headers,
                    json={"field_name": BD_INVITATION_CREATOR_FIELD, "type": 1},
                ),
                "rename collection creator field",
            )
        _data(
            await client.put(
                f"{field_path}/{_field_id(owner, 'owner')}",
                headers=headers,
                json=_owner_field_body(bd_names),
            ),
            "configure collection BD field",
        )
        if _field_by_name(fields, BD_INVITATION_REMARK_FIELD) is None:
            _data(
                await client.post(
                    field_path,
                    headers=headers,
                    json={"field_name": BD_INVITATION_REMARK_FIELD, "type": 1},
                ),
                "create collection remark field",
            )
        verified = await _list_items(client, field_path, headers)
        _verify_fields(verified, bd_names)
        record_data = _data(
            await client.get(
                field_path.removesuffix("/fields") + "/records",
                headers=headers,
                params={"page_size": 1, "automatic_fields": True},
            ),
            "read collection records",
        )
        print(
            json.dumps(
                {
                    "apply": True,
                    "table_id": arguments.table_id,
                    "fields": [
                        BD_INVITATION_CREATOR_FIELD,
                        BD_INVITATION_OWNER_FIELD,
                        SUBMITTED_AT_FIELD,
                        SUBMITTER_FIELD,
                        BD_INVITATION_REMARK_FIELD,
                    ],
                    "bd_options": list(bd_names),
                    "record_count": record_data.get("total"),
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
