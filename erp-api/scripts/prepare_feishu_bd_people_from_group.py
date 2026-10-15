from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError

TARGET_NAMES = frozenset({"李鸿程", "吴洵涛", "刘诚"})
BD_NAME_FIELD = "BD姓名"
BD_PERSON_FIELD = "飞书人员"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        raise RuntimeError("Feishu sample connection is not configured.")
    client = FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=args.table_id,
    )
    token = await client.tenant_access_token()
    chats = await _list_all(client, token, "/open-apis/im/v1/chats")
    matches = []
    accessible_member_lists = 0
    max_target_match = 0
    for chat in chats:
        chat_id = chat.get("chat_id") if isinstance(chat, dict) else None
        if not isinstance(chat_id, str) or not chat_id:
            continue
        try:
            members = await _list_all(
                client,
                token,
                f"/open-apis/im/v1/chats/{chat_id}/members",
                extra_params={"member_id_type": "open_id"},
            )
        except FeishuSampleError:
            continue
        accessible_member_lists += 1
        people = {
            item.get("name"): item.get("member_id")
            for item in members
            if isinstance(item, dict) and item.get("name") in TARGET_NAMES
        }
        max_target_match = max(max_target_match, len(people))
        if set(people) == TARGET_NAMES:
            matches.append(people)
    if len(matches) != 1:
        print(
            json.dumps(
                {
                    "status": "not_unique",
                    "matching_groups": len(matches),
                    "visible_chats": len(chats),
                    "accessible_member_lists": accessible_member_lists,
                    "max_target_match": max_target_match,
                }
            )
        )
        return
    people = matches[0]
    print(
        json.dumps(
            {
                "status": "matched",
                "matched_names": sorted(people),
                "apply": args.apply,
            }
        )
    )
    if not args.apply:
        return
    records = await client.list_record_snapshots()
    by_name = {
        record.snapshot.fields.get(BD_NAME_FIELD): record
        for record in records
        if record.snapshot.fields.get(BD_NAME_FIELD) in TARGET_NAMES
    }
    if set(by_name) != TARGET_NAMES:
        raise RuntimeError("Feishu BD roster rows are incomplete.")
    for name in sorted(TARGET_NAMES):
        await client._request(
            "PUT",
            client._record_path(by_name[name].record_id),
            token=token,
            json={"fields": {BD_PERSON_FIELD: [{"id": people[name]}]}},
        )
    verified = await client.list_record_snapshots()
    populated = {
        record.snapshot.fields.get(BD_NAME_FIELD)
        for record in verified
        if record.snapshot.fields.get(BD_PERSON_FIELD)
    }
    if not TARGET_NAMES <= populated:
        raise RuntimeError("Feishu BD people writeback was not verified.")
    print(json.dumps({"status": "updated", "updated_count": len(TARGET_NAMES)}))


async def _list_all(client, token, path, *, extra_params=None):
    items = []
    page_token = None
    while True:
        params = {"page_size": 100, **(extra_params or {})}
        if page_token:
            params["page_token"] = page_token
        data = await client._request("GET", path, token=token, params=params)
        page_items = data.get("items")
        if not isinstance(page_items, list):
            raise TypeError("Feishu list response is invalid.")
        items.extend(page_items)
        if data.get("has_more") is not True:
            return items
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token:
            raise RuntimeError("Feishu list pagination is invalid.")


if __name__ == "__main__":
    asyncio.run(main())
