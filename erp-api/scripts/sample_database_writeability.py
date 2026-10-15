"""Read-only preflight for sample watcher write access."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database


async def database_is_writable() -> bool:
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            setting = await session.scalar(
                text("SELECT current_setting('transaction_read_only')")
            )
            return setting == "off"
    finally:
        await database.dispose()


if __name__ == "__main__":
    print("true" if asyncio.run(database_is_writable()) else "false")
