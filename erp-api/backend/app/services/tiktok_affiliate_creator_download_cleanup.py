"""Clean up only an owned creator export download artifact."""

import asyncio
from pathlib import Path

from playwright.async_api import Download

from backend.app.services.tiktok_affiliate_analytics_page_control import capture_log


async def delete_download(download: Download | None) -> None:
    if download is None:
        return
    local_path: Path | None = None
    try:
        path = await download.path()
        if path:
            local_path = Path(path)
    except Exception:  # noqa: BLE001 -- browser cleanup remains preferred
        local_path = None
    try:
        await download.delete()
        return
    except Exception:  # noqa: BLE001 -- fall back to the exact download path
        if local_path is None:
            capture_log("affiliate_creator_export_cleanup_failed")
            return
    if local_path is not None:
        try:
            await asyncio.to_thread(local_path.unlink, missing_ok=True)
            return
        except OSError:
            capture_log("affiliate_creator_export_cleanup_failed")
            return
    capture_log("affiliate_creator_export_cleanup_failed")
