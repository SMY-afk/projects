from __future__ import annotations

import re

from erp_api.services.sample_cooperation_parsing import (
    normalize_account_name,
    plain_text,
)

_CREATOR_ID_SEPARATOR = re.compile(r"[,，;；、\r\n]+")
_CREATOR_ID_LIST_PREFIX = re.compile(r"^\s*(?:\d{1,4}\s*[.．、)）]\s+|[-•]\s+)")
_CREATOR_ID_LIST_MARKER = re.compile(r"^\s*\d{1,4}\s*[.．、)）]\s*$")
_CREATOR_ID_NUMBERED_PREFIX = re.compile(
    r"(?<!\S)(?P<number>\d{1,4})\s*[.．、)）]\s*(?=\S)"
)


def requires_creator_id_expansion(value: str) -> bool:
    return bool(
        re.search(r"[\s,，;；、]", value) or _CREATOR_ID_LIST_PREFIX.match(value)
    )


def split_creator_ids(value: object) -> tuple[str, ...]:
    text = plain_text(value)
    if not text:
        return ()
    numbered_items = tuple(_CREATOR_ID_NUMBERED_PREFIX.finditer(text))
    numbers = tuple(int(item.group("number")) for item in numbered_items)
    compact_numbered_list = len(numbers) >= 2 and numbers == tuple(
        range(numbers[0], numbers[0] + len(numbers))
    )
    if compact_numbered_list:
        raw_items = tuple(
            text[item.end() : numbered_items[index + 1].start()]
            if index + 1 < len(numbered_items)
            else text[item.end() :]
            for index, item in enumerate(numbered_items)
        )
    else:
        raw_items = tuple(_CREATOR_ID_SEPARATOR.split(text))
    items = tuple(
        _CREATOR_ID_LIST_PREFIX.sub("", item)
        for item in raw_items
        if not _CREATOR_ID_LIST_MARKER.fullmatch(item)
    )
    return tuple(
        dict.fromkeys(
            creator_id for item in items if (creator_id := normalize_account_name(item))
        )
    )
