from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from uuid import uuid4

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_analytics_services
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)


def _arguments():
    parser = argparse.ArgumentParser(description="Run one official affiliate sync.")
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--resource", choices=("creators", "videos"), required=True)
    parser.add_argument("--from", dest="window_start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="window_end", type=date.fromisoformat, required=True)
    return parser.parse_args()


async def _shop(database, name):
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(Shop).where(
                    Shop.shop_name == name,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
        ).scalars().all()
    if len(rows) != 1:
        raise ValueError("Shop name must resolve to one active TikTok shop.")
    return rows[0]


async def _run(args):
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        shop = await _shop(database, args.shop_name)
        service = build_analytics_services(settings, database).get(
            "official_affiliate_sync_service"
        )
        if service is None:
            raise RuntimeError("Official affiliate sync service is unavailable.")
        query = AffiliateCenterQuery(
            resource=AffiliateCenterResource(args.resource),
            shop_id=shop.id,
            window_start=args.window_start,
            window_end=args.window_end,
            shop_timezone=shop.timezone,
            currency=(shop.currency or "USD").upper(),
            filters={},
        )
        job_id = f"manual-official-affiliate:{shop.id}:{uuid4()}"
        result = await service.sync(shop.tenant_id, query, job_id=job_id)
        return {"status": "succeeded", "resource": args.resource, "result": result}
    finally:
        await database.dispose()


def main():
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, default=str, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
