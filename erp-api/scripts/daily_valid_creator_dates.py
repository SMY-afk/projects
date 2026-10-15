"""Per-shop source cutoffs for the daily valid-creator reconciliation."""

from __future__ import annotations

from datetime import date

from scripts.daily_valid_creator_core import SHOP_LINES

ShopCutoffs = dict[str, dict[str, date]]


def parse_shop_cutoffs(raw: list[str], *, today: date | None = None) -> ShopCutoffs:
    """Parse independent creator, video, and live cutoffs for five shops."""
    cutoffs: ShopCutoffs = {}
    for value in raw:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4 or parts[0] not in SHOP_LINES:
            raise ValueError("Shop cutoff must be NAME,CREATOR_END,VIDEO_END,LIVE_END")
        name = parts[0]
        if name in cutoffs:
            raise ValueError(f"{name}: duplicate shop cutoff")
        try:
            creators, videos, live = (date.fromisoformat(part) for part in parts[1:])
        except ValueError as error:
            raise ValueError(f"{name}: invalid cutoff date") from error
        if today and any(day > today for day in (creators, videos, live)):
            raise ValueError(f"{name}: source cutoff is in the future")
        cutoffs[name] = {
            "creators": creators,
            "videos": videos,
            "liveAccounts": live,
        }
    if set(cutoffs) != set(SHOP_LINES):
        raise ValueError("Cutoffs must contain exactly the five shops")
    return cutoffs
