"""Read-only preflight for the configured Feishu sample app and copied Base."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from dotenv import dotenv_values

from erp_api.services.feishu_sample_fields import REQUIRED_SAMPLE_FIELDS
from erp_api.services.feishu_bd_roster_provider import REQUIRED_ROSTER_FIELDS


API = "https://example.invalid/configure-resource"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def required(config: dict, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"MISSING_CONFIG={key}")
    return value


async def request(client: httpx.AsyncClient, method: str, path: str, label: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code != 200:
        raise RuntimeError(f"FEISHU_HTTP_ERROR LABEL={label} STATUS={response.status_code}")
    payload = response.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"FEISHU_API_ERROR LABEL={label} CODE={payload.get('code')}")
    return payload


async def paged_items(client, path: str, label: str) -> list[dict]:
    items = []
    page_token = None
    seen = set()
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        data = (await request(client, "GET", path, label, params=params)).get("data") or {}
        page = data.get("items")
        if not isinstance(page, list):
            raise RuntimeError(f"INVALID_PAGE LABEL={label}")
        items.extend(page)
        if data.get("has_more") is not True:
            return items
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token or page_token in seen:
            raise RuntimeError(f"INVALID_PAGINATION LABEL={label}")
        seen.add(page_token)


def person_id(value) -> str | None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return None
    result = value[0].get("id") or value[0].get("open_id")
    return result if isinstance(result, str) and result.startswith("ou_") else None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    config = dotenv_values(".env")
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    tables = {name: info["new_table_id"] for name, info in artifact["tables"].items()}
    app_id = required(config, "FEISHU_APP_ID")
    if app_id != required(config, "FEISHU_NEW_APP_ID"):
        raise RuntimeError("APP_ID_NOT_NEW_APP")
    app_secret = required(config, "FEISHU_APP_SECRET")
    base = required(config, "FEISHU_SAMPLE_BASE_TOKEN")
    if required(config, "FEISHU_SAMPLE_TABLE_ID") != tables["本土店达人申请"]:
        raise RuntimeError("DEFAULT_TABLE_NOT_COPIED_BASE")
    shop_map = json.loads(required(config, "FEISHU_SAMPLE_SHOP_TABLE_IDS"))
    expected_shop_tables = {
        tables[name] for name in (
            "跨境3样品申请", "跨境4样品申请", "跨境7店-样品申请", "跨境12样品申请"
        )
    }
    if len(shop_map) != 4 or set(shop_map.values()) != expected_shop_tables:
        raise RuntimeError("SHOP_TABLES_NOT_COPIED_BASE")
    for key, name in (
        ("FEISHU_SAMPLE_LIBRARY_TABLE_ID", "样品库"),
        ("FEISHU_BD_ROSTER_TABLE_ID", "BD名单"),
        ("FEISHU_BD_ASSIGNMENT_RECORD_TABLE_ID", "达人分配记录"),
        ("FEISHU_BD_INVITATION_PROTECTION_TABLE_ID", "BD自主邀约收集表"),
        ("FEISHU_DAILY_VALID_CREATOR_TABLE_ID", "（每日更新）有效达人"),
    ):
        if required(config, key) != tables[name]:
            raise RuntimeError(f"TABLE_NOT_COPIED_BASE={key}")
    group_id = required(config, "FEISHU_SAMPLE_NOTIFICATION_GROUP_CHAT_ID")
    record_url = required(config, "FEISHU_SAMPLE_RECORD_URL_TEMPLATE")
    if base not in record_url or "{record_id}" not in record_url:
        raise RuntimeError("RECORD_URL_NOT_COPIED_BASE")
    allowed_names = {
        value.strip() for value in required(config, "FEISHU_SAMPLE_AUTO_ASSIGNMENT_BD_NAMES").split(",")
        if value.strip()
    }
    if not allowed_names:
        raise RuntimeError("EMPTY_BD_ALLOWLIST")
    print(f"LOCAL_APP_AND_COPIED_BASE_CONFIG_OK APP_SHA12={digest(app_id)} TABLES={len(tables)} SHOP_MAP={len(shop_map)}")
    async with httpx.AsyncClient(base_url=API, timeout=20) as client:
        token_payload = await request(
            client, "POST", "/open-apis/auth/v3/tenant_access_token/internal", "token",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        token = token_payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("INVALID_TENANT_TOKEN")
        client.headers["Authorization"] = f"Bearer {token}"
        print("FEISHU_APP_AUTH_OK")
        for name in ("本土店达人申请", "跨境3样品申请", "跨境4样品申请", "跨境7店-样品申请", "跨境12样品申请"):
            fields = await paged_items(
                client, f"/open-apis/bitable/v1/apps/{base}/tables/{tables[name]}/fields", "sample_fields"
            )
            names = {field.get("field_name") for field in fields}
            if not REQUIRED_SAMPLE_FIELDS.issubset(names):
                raise RuntimeError(f"SAMPLE_FIELDS_MISSING={name}")
            print(f"SAMPLE_TABLE_READ_OK NAME={name} FIELDS={len(fields)}")
        roster_fields = await paged_items(
            client, f"/open-apis/bitable/v1/apps/{base}/tables/{tables['BD名单']}/fields", "roster_fields"
        )
        if not REQUIRED_ROSTER_FIELDS.issubset({field.get("field_name") for field in roster_fields}):
            raise RuntimeError("ROSTER_FIELDS_MISSING")
        roster = await paged_items(
            client, f"/open-apis/bitable/v1/apps/{base}/tables/{tables['BD名单']}/records", "roster_records"
        )
        found = {}
        for record in roster:
            fields = record.get("fields") or {}
            name = fields.get("BD姓名")
            if isinstance(name, str) and name in allowed_names:
                found[name] = person_id(fields.get("飞书人员"))
        if set(found) != allowed_names or any(value is None for value in found.values()):
            raise RuntimeError(f"BD_RECIPIENTS_INVALID FOUND={len(found)} REQUIRED={len(allowed_names)}")
        print(f"BD_RECIPIENTS_READ_OK COUNT={len(found)} OPEN_ID_HASHES={','.join(sorted(digest(value) for value in found.values()))}")
        chat_payload = await request(
            client, "GET", f"/open-apis/im/v1/chats/{group_id}", "notification_chat"
        )
        chat = chat_payload.get("data") or {}
        nested_chat = chat.get("chat") if isinstance(chat.get("chat"), dict) else {}
        returned_id = chat.get("chat_id") or nested_chat.get("chat_id")
        if returned_id is not None and returned_id != group_id:
            raise RuntimeError("NOTIFICATION_CHAT_ID_MISMATCH")
        raw_bot_count = chat.get("bot_count")
        bot_count = int(raw_bot_count) if isinstance(raw_bot_count, (int, str)) and str(raw_bot_count).isdigit() else 0
        if bot_count < 1 or chat.get("chat_status") != "normal":
            raise RuntimeError("NOTIFICATION_CHAT_NOT_READY")
        print(
            f"NOTIFICATION_CHAT_READ_OK CHAT_SHA12={digest(group_id)} "
            f"BOT_COUNT={bot_count} STATUS={chat.get('chat_status')}"
        )
    print("FEISHU_READ_ONLY_PREFLIGHT_OK NO_MESSAGES_SENT")


if __name__ == "__main__":
    asyncio.run(main())
