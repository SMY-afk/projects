"""Read-only direct creator/video date probe for the four HubStudio shops."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from scripts.probe_daily_valid_creator_online import probe_shop

SHOPS = (
    ("跨境3", "9622543325839925006"),
    ("跨境4", "9768147009521852682"),
    ("跨境7", "9121478993551097445"),
    ("跨境12", "9472478445887813622"),
)


async def main() -> None:
    rows = []
    for name, platform_shop_id in SHOPS:
        cdp_url = await discover_hubstudio_cdp_url(
            current_url=None, expected_platform_shop_id=platform_shop_id
        )
        if cdp_url is None:
            raise RuntimeError(f"{name}: verified shop browser unavailable")
        rows.append(await probe_shop(name, platform_shop_id, cdp_url))
    print(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    asyncio.run(main())
