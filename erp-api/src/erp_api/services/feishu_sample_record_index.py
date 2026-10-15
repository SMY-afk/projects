from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from erp_api.services.feishu_sample_errors import FeishuSampleError

SYNC_KEY_FIELD = "同步键（系统）"
FeishuRecordPageFetcher = Callable[[str | None], Awaitable[dict[str, Any]]]


async def build_record_sync_key_map(
    fetch_page: FeishuRecordPageFetcher,
) -> dict[str, str]:
    sync_key_to_record_id: dict[str, str] = {}
    expected_total: int | None = None
    records_read = 0
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        data = await fetch_page(page_token)
        total = data.get("total")
        if total is not None:
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise FeishuSampleError("Feishu record total is invalid.")
            if expected_total is not None and total != expected_total:
                raise FeishuSampleError("Feishu record total changed between pages.")
            expected_total = total
        items = data.get("items")
        if items is None and total == 0:
            items = []
        if not isinstance(items, list):
            raise FeishuSampleError("Feishu record list is invalid.")
        for item in items:
            records_read += 1
            sync_key, record_id = _record_identity(item)
            if sync_key is None:
                continue
            if sync_key in sync_key_to_record_id:
                raise FeishuSampleError(f"Feishu sync key is duplicated: {sync_key}.")
            sync_key_to_record_id[sync_key] = record_id
        has_more = data.get("has_more")
        if not isinstance(has_more, bool):
            raise FeishuSampleError("Feishu record pagination flag is invalid.")
        if not has_more:
            break
        next_token = data.get("page_token")
        if (
            not isinstance(next_token, str)
            or not next_token
            or next_token in seen_tokens
        ):
            raise FeishuSampleError("Feishu record pagination is incomplete.")
        seen_tokens.add(next_token)
        page_token = next_token
    if expected_total is not None and records_read != expected_total:
        raise FeishuSampleError("Feishu record total is incomplete.")
    return sync_key_to_record_id


def _record_identity(item: object) -> tuple[str | None, str]:
    if not isinstance(item, dict):
        raise FeishuSampleError("Feishu record item is invalid.")
    record_id = item.get("record_id")
    fields = item.get("fields")
    if not isinstance(record_id, str) or not record_id or not isinstance(fields, dict):
        raise FeishuSampleError("Feishu record item is invalid.")
    sync_key = fields.get(SYNC_KEY_FIELD)
    if sync_key in (None, ""):
        return None, record_id
    if not isinstance(sync_key, str) or not sync_key.strip():
        raise FeishuSampleError("Feishu sync key is invalid.")
    return sync_key.strip(), record_id
