"""Read-only identity and row-count check using the daily-sync app credentials."""

from __future__ import annotations

import asyncio

from erp_api.core.config import get_settings
from erp_api.services.feishu_client import FeishuClient
from scripts.daily_valid_creator_io import target_rows, verify_target_identity


async def main() -> None:
    settings = get_settings()
    if not settings.feishu_new_app_id or not settings.feishu_new_app_secret:
        raise RuntimeError("ECS daily-sync Feishu app credentials are missing")
    client = FeishuClient(
        app_id=settings.feishu_new_app_id,
        app_secret=settings.feishu_new_app_secret.get_secret_value(),
        business_type="daily_valid_creator_sync",
    )
    await verify_target_identity(client)
    rows = await target_rows(client)
    print(f"DAILY_FEISHU_TARGET_OK ROWS={len(rows)} NO_WRITES")


if __name__ == "__main__":
    asyncio.run(main())
