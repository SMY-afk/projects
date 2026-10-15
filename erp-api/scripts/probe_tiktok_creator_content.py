from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_creator_content_probe import (
    TikTokCreatorContentProbe,
    evaluate_creator_preflight,
)
from erp_api.services.tiktok_transport import TikTokTransport
from erp_api.services.token_cipher import TokenCipher


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sanitized, read-only TikTok creator content probe."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--creator-env",
        action="store_true",
        help="Use one-time TIKTOK_CREATOR_PROBE_* environment variables.",
    )
    mode.add_argument(
        "--seller-negative",
        action="store_true",
        help="Prove that the existing seller token cannot act as a creator.",
    )
    parser.add_argument("--shop-name", default="Akeleo Fun Toys")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _base_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok API endpoint is not configured correctly.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _creator_environment() -> tuple[str, str | None, list[str]]:
    access_token = os.getenv("TIKTOK_CREATOR_PROBE_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise ValueError("TIKTOK_CREATOR_PROBE_ACCESS_TOKEN is required.")
    user_type = os.getenv("TIKTOK_CREATOR_PROBE_USER_TYPE")
    scopes = [
        scope.strip()
        for scope in os.getenv("TIKTOK_CREATOR_PROBE_GRANTED_SCOPES", "").split(",")
        if scope.strip()
    ]
    return access_token, user_type, scopes


async def _seller_environment(
    database: Database, cipher: TokenCipher, shop_name: str
) -> tuple[str, str, list[str]]:
    async with database.system_session_factory() as session:
        result = await session.execute(
            select(ShopConnection)
            .join(Shop, Shop.id == ShopConnection.shop_id)
            .where(
                Shop.shop_name == shop_name,
                Shop.platform == "tiktok",
                Shop.status == "active",
                ShopConnection.auth_status == "authorized",
            )
        )
        matches = result.scalars().all()
    if len(matches) != 1 or not matches[0].access_token_ciphertext:
        raise ValueError("The seller-negative target must be one authorized shop.")
    connection = matches[0]
    return (
        cipher.decrypt(connection.access_token_ciphertext),
        "0",
        list(connection.scopes),
    )


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if not (
        settings.tiktok_app_key
        and settings.tiktok_app_secret
        and settings.tiktok_shop_identity_url
    ):
        raise ValueError("TikTok API settings are required.")

    database: Database | None = None
    try:
        if args.creator_env:
            access_token, user_type, scopes = _creator_environment()
            mode = "creator_positive"
        else:
            if not settings.tiktok_token_encryption_key:
                raise ValueError("TIKTOK_TOKEN_ENCRYPTION_KEY is required.")
            database = Database(settings.database_url)
            cipher = TokenCipher(
                settings.tiktok_token_encryption_key.get_secret_value()
            )
            access_token, user_type, scopes = await _seller_environment(
                database, cipher, args.shop_name
            )
            mode = "seller_negative_control"

        transport = TikTokTransport(
            base_url=_base_url(settings.tiktok_shop_identity_url),
            app_key=settings.tiktok_app_key,
            app_secret=settings.tiktok_app_secret.get_secret_value(),
            timeout_seconds=settings.tiktok_request_timeout_seconds,
            max_retries=0,
        )
        probes = await TikTokCreatorContentProbe(transport).run_read_only(
            access_token=access_token
        )
        return {
            "executedAt": datetime.now(UTC).isoformat(),
            "mode": mode,
            "preflight": evaluate_creator_preflight(
                user_type=user_type, granted_scopes=scopes
            ),
            "probes": probes,
        }
    finally:
        if database is not None:
            await database.dispose()


def main() -> None:
    args = _arguments()
    try:
        result = asyncio.run(_run(args))
    except Exception as error:
        raise SystemExit(str(error)) from error
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{output}\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
