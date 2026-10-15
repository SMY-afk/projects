from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.user import User
from erp_api.services.tiktok_authorization import TikTokAuthorizationService

DEFAULT_CREATOR_AUTHORIZATION_URL = "https://shop.tiktok.com/alliance/creator/auth"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a short-lived TikTok Creator authorization shortcut."
    )
    parser.add_argument("--username", default="admin")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


async def _user_context(database: Database, username: str):
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(User.id, User.tenant_id).where(
                    User.username == username, User.status == "active"
                )
            )
        ).all()
    if len(rows) != 1:
        raise ValueError("Username must resolve to exactly one active ERP user.")
    return rows[0]


async def _run(args: argparse.Namespace) -> dict[str, str]:
    settings = get_settings()
    if not (
        settings.tiktok_service_id
        and settings.tiktok_authorization_url
        and settings.tiktok_app_key
    ):
        raise ValueError(
            "TikTok seller and creator authorization settings are required."
        )
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        user_id, tenant_id = await _user_context(database, args.username)
        service = TikTokAuthorizationService(
            redis,
            service_id=settings.tiktok_service_id,
            authorization_url=settings.tiktok_authorization_url,
            app_key=settings.tiktok_app_key,
            creator_authorization_url=(
                settings.tiktok_creator_authorization_url
                or DEFAULT_CREATOR_AUTHORIZATION_URL
            ),
            state_ttl_seconds=settings.tiktok_oauth_state_ttl_seconds,
        )
        authorization_url = await service.create_creator_authorization_url(
            user_id, tenant_id
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"[InternetShortcut]\nURL={authorization_url}\n",
            encoding="utf-8",
        )
        expires_at = datetime.now(UTC) + timedelta(
            seconds=settings.tiktok_oauth_state_ttl_seconds
        )
        return {
            "output": str(args.output.resolve()),
            "expiresAt": expires_at.isoformat(),
        }
    finally:
        await redis.aclose()
        await database.dispose()


def main() -> None:
    args = _arguments()
    try:
        result = asyncio.run(_run(args))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
