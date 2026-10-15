from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", action="append", type=UUID, required=True)
    return parser.parse_args()


async def main(shop_ids: list[UUID]) -> None:
    if len(shop_ids) != len(set(shop_ids)):
        raise ValueError("Shop IDs must be unique.")
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        services = build_sample_application_services(settings, database)
        router = services.get("feishu_sample_client_router")
        if router is None:
            raise RuntimeError("Feishu sample client router is unavailable.")
        result = {}
        for shop_id in shop_ids:
            client = router.for_shop(shop_id)
            sync_keys = await client.list_record_sync_key_map()
            result[str(shop_id)] = {
                "record_sync_key_count": len(sync_keys),
                "duplicate_sync_key_count": 0,
            }
        print(json.dumps(result, sort_keys=True))
    finally:
        await database.dispose()


if __name__ == "__main__":
    arguments = _arguments()
    asyncio.run(main(arguments.shop_id))
