from __future__ import annotations

SHOP_DISPLAY_SUFFIXES = {
    "fanfu toy tool": "跨境3",
    "Akeleo-Drive": "跨境7",
    "Akeleo Fun Toys": "跨境4",
    "NEOPUP": "跨境12",
    "Akeleo Toys": "本土店",
}


def sample_shop_display_name(shop_name: str) -> str:
    suffix = SHOP_DISPLAY_SUFFIXES.get(shop_name)
    return f"{shop_name}（{suffix}）" if suffix else shop_name
