from __future__ import annotations

from collections.abc import Mapping, Sequence
from unicodedata import category


def display_application_id(
    platform_application_id: str,
    *,
    raw_payload: object = None,
    source_application_ids: Sequence[object] = (),
) -> str:
    """Expose TikTok item application IDs while keeping the group key internal."""
    if not platform_application_id.startswith("creator-group:"):
        return platform_application_id
    values: object = source_application_ids
    if not values and isinstance(raw_payload, Mapping):
        values = raw_payload.get("source_item_ids")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ""
    normalized = tuple(
        dict.fromkeys(
            value.strip()
            for value in values
            if isinstance(value, str) and value.strip()
        )
    )
    return "、".join(normalized)


def display_creator_name(nickname: str | None, username: str | None) -> str:
    """Prefer TikTok nickname, but never expose an invisible-only display value."""
    for value in (nickname, username):
        if not isinstance(value, str) or not (cleaned := value.strip()):
            continue
        if any(category(character)[0] not in {"C", "Z"} for character in cleaned):
            return cleaned
    return ""
