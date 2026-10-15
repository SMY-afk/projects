"""Resolve a running, exact-shop Ziniao CDP without starting its browser."""

from __future__ import annotations

from hashlib import blake2b
from pathlib import Path
from urllib.parse import urlsplit

from backend.app.services.hubstudio_cdp import (
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from erp_api.core.config import get_settings
from scripts.ingest_creator_xlsx import _running_browser


async def resolve_ziniao_export_source(platform_shop_id: str) -> tuple[str, str]:
    settings = get_settings()
    browser = await _running_browser(settings)
    download_path = Path(str(browser.get("downloadPath") or ""))
    configured_name = (settings.ziniao_akeleo_browser_name or "").strip()
    if not configured_name or download_path.name != configured_name:
        raise RuntimeError("Running Ziniao browser is not the configured Akeleo Toys")
    port = int(browser["debuggingPort"])
    cdp_url = f"http://127.0.0.1:{port}"
    if not await probe_cdp_endpoint(cdp_url):
        raise RuntimeError("Running Ziniao CDP is unavailable")
    if await read_cdp_platform_shop_ids(cdp_url) != frozenset({platform_shop_id}):
        raise RuntimeError("Running Ziniao CDP shop identity is missing or mixed")
    digest = blake2b(
        str(download_path).encode("utf-8"), digest_size=8
    ).digest()
    environment_id = str(int.from_bytes(digest, "big"))
    return cdp_url, environment_id


async def verified_ziniao_download_dir(cdp_url: str) -> Path:
    """Resolve only the active, configured Ziniao browser's download directory."""
    settings = get_settings()
    browser = await _running_browser(settings)
    directory = Path(str(browser.get("downloadPath") or ""))
    if (
        int(browser["debuggingPort"]) != urlsplit(cdp_url).port
        or directory.name != settings.ziniao_akeleo_browser_name
        or not directory.is_dir()
    ):
        raise RuntimeError("Ziniao download path differs from the verified browser")
    return directory
