from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping


def page_records(
    resource: str, payload: Mapping[str, object]
) -> tuple[int, list[str], int | None]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return 0, [], None
    if resource == "creators":
        return _creator_page_records(data)
    return _video_page_records(data)


def pagination_has_more(payload: Mapping[str, object]) -> bool | None:
    value = _find_key(payload, "hasmore")
    return value if isinstance(value, bool) else None


def pagination_cursor(payload: Mapping[str, object]) -> tuple[bool, str | None]:
    for normalized in ("nextcursor", "cursor"):
        found, value = _find_key_with_presence(payload, normalized)
        if found:
            if value is None:
                return True, None
            if isinstance(value, str):
                return True, value.strip() or None
    return False, None


def cursor_hash(cursor: str) -> str:
    digest = hashlib.sha256(cursor.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _creator_page_records(
    data: Mapping[str, object],
) -> tuple[int, list[str], int | None]:
    rows: list[object] = []
    total: int | None = None
    for segment in _mapping_items(data.get("segments")):
        control = segment.get("list_control")
        if isinstance(control, Mapping):
            pagination = control.get("next_pagination")
            if isinstance(pagination, Mapping):
                total = _integer_or_none(pagination.get("total"))
        for timed_list in _mapping_items(segment.get("timed_lists")):
            stats = timed_list.get("stats")
            if isinstance(stats, list):
                rows.extend(stats)
    return len(rows), _record_keys(rows, ("id", "handle")), total


def _video_page_records(
    data: Mapping[str, object],
) -> tuple[int, list[str], int | None]:
    rows: list[object] = []
    total: int | None = None
    for segment in _mapping_items(data.get("video_list_segments_v2")):
        total = _integer_or_none(segment.get("total"))
        performances = segment.get("video_performances")
        if isinstance(performances, list):
            rows.extend(performances)
    keys: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        video_info = row.get("video_info")
        if isinstance(video_info, Mapping):
            key = _scalar_key(video_info.get("item_id"))
            if key is not None:
                keys.append(key)
    return len(rows), keys, total


def _record_keys(rows: list[object], fields: tuple[str, ...]) -> list[str]:
    keys: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for field_name in fields:
            key = _scalar_key(row.get(field_name))
            if key is not None:
                keys.append(key)
                break
    return keys


def _mapping_items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _find_key(value: object, normalized_key: str) -> object:
    return _find_key_with_presence(value, normalized_key)[1]


def _find_key_with_presence(value: object, normalized_key: str) -> tuple[bool, object]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and _normalize_key(key) == normalized_key:
                return True, item
            found, nested = _find_key_with_presence(item, normalized_key)
            if found:
                return True, nested
    elif isinstance(value, list):
        for item in value:
            found, nested = _find_key_with_presence(item, normalized_key)
            if found:
                return True, nested
    return False, None


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.casefold())


def _scalar_key(value: object) -> str | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
