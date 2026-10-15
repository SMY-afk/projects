"""Read-only proof that the running Ziniao browser belongs to Akeleo Toys."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

import httpx

from backend.app.services.hubstudio_cdp import (
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from erp_api.core.config import get_settings
from scripts.ingest_creator_xlsx import _running_browser

PLATFORM_SHOP_ID = "9136806951995371293"


async def main() -> None:
    settings = get_settings()
    browser = await _running_browser(settings)
    print("BROWSER_FIELDS=" + ",".join(sorted(browser)))
    name = Path(str(browser.get("downloadPath") or "")).name
    expected = (settings.ziniao_akeleo_browser_name or "").strip()
    if not expected or name != expected:
        raise RuntimeError("Running Ziniao browser identity differs from Akeleo Toys")
    port = int(browser["debuggingPort"])
    url = f"http://127.0.0.1:{port}"
    if not await probe_cdp_endpoint(url):
        raise RuntimeError("Ziniao CDP is unavailable")
    identities = await read_cdp_platform_shop_ids(url)
    if identities != frozenset({PLATFORM_SHOP_ID}):
        raise RuntimeError("Ziniao CDP shop identity is missing or mixed")
    print(f"ZINIAO_SOURCE_OK PORT={port} SHOP={PLATFORM_SHOP_ID}")
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{url}/json/list")
        response.raise_for_status()
        for target in response.json():
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            split = urlsplit(str(target.get("url") or ""))
            if split.hostname and "tiktok" in split.hostname:
                shop_ids = parse_qs(split.query).get("shop_id", [])
                print(f"PAGE={split.hostname}{split.path} SHOP_IDS={','.join(shop_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
