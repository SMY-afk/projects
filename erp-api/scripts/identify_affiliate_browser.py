from __future__ import annotations

import argparse
import asyncio
import json
from urllib.request import urlopen
from uuid import UUID

from sqlalchemy import select

from backend.app.services.tiktok_affiliate_intent_page import browser_platform_shop_ids
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Match an ERP shop to a local HubStudio CDP port safely."
    )
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--ports", type=int, nargs="+", required=True)
    return parser.parse_args()


def _platform_shop_ids(port: int) -> frozenset[str]:
    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as response:
        tabs = json.load(response)
    pages = [
        _Page(tab["url"])
        for tab in tabs
        if tab.get("type") == "page" and isinstance(tab.get("url"), str)
    ]
    return browser_platform_shop_ids(pages)  # type: ignore[arg-type]


async def _run(arguments: argparse.Namespace) -> list[dict[str, object]]:
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            shop = await session.scalar(
                select(Shop).where(
                    Shop.id == arguments.shop_id,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
            known_shops = (
                await session.execute(
                    select(Shop.shop_name, Shop.platform_shop_id).where(
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                    )
                )
            ).all()
        if shop is None:
            raise ValueError("Active TikTok shop was not found.")
        result = []
        for port in arguments.ports:
            try:
                platform_ids = _platform_shop_ids(port)
                result.append(
                    {
                        "port": port,
                        "matched": shop.platform_shop_id in platform_ids,
                        "affiliateShopCount": len(platform_ids),
                        "knownShopNames": sorted(
                            name
                            for name, platform_shop_id in known_shops
                            if platform_shop_id in platform_ids
                        ),
                    }
                )
            except Exception:  # noqa: BLE001 -- report unavailable local sessions
                result.append(
                    {"port": port, "matched": False, "affiliateShopCount": 0}
                )
        return result
    finally:
        await database.dispose()


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
