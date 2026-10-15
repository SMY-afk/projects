from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date as calendar_date
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_bestseller_probe import TikTokBestsellerProbe
from erp_api.services.tiktok_transport import TikTokTransport
from erp_api.services.token_cipher import TokenCipher


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe TikTok bestselling APIs without logging response values."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--shop-id", type=UUID)
    target.add_argument("--shop-name")
    parser.add_argument("--date", dest="reference_date")
    parser.add_argument("--time-slot", choices=("1D", "7D", "30D"), default="7D")
    parser.add_argument("--currency", choices=("USD", "LOCAL"), default="USD")
    parser.add_argument(
        "--author-type",
        choices=("ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"),
        default="ALL",
    )
    return parser.parse_args()


def _base_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok API endpoint is not configured correctly.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _completed_date(timezone_name: object) -> str:
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("Shop timezone is required when --date is omitted.")
    return (
        datetime.now(ZoneInfo(timezone_name)).date() - timedelta(days=1)
    ).isoformat()


async def _resolve_shop(
    database: Database,
    cipher: TokenCipher,
    shop_id: UUID | None,
    shop_name: str | None,
) -> tuple[object, str, str]:
    target = Shop.id == shop_id if shop_id is not None else Shop.shop_name == shop_name
    async with database.system_session_factory() as session:
        result = await session.execute(
            select(Shop, ShopConnection)
            .join(ShopConnection, ShopConnection.shop_id == Shop.id)
            .where(
                target,
                Shop.platform == "tiktok",
                Shop.status == "active",
                ShopConnection.auth_status == "authorized",
            )
        )
        matches = result.all()
    if len(matches) != 1:
        raise ValueError("The probe target must resolve to exactly one active shop.")
    shop, connection = matches[0]
    if not connection.access_token_ciphertext or not connection.shop_ciphertext:
        raise ValueError("The target shop has no usable authorized connection.")
    return (
        shop.timezone,
        cipher.decrypt(connection.access_token_ciphertext),
        cipher.decrypt(connection.shop_ciphertext),
    )


async def _run(args: argparse.Namespace) -> list[dict[str, object]]:
    settings = get_settings()
    required = (
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_shop_identity_url,
        settings.tiktok_token_encryption_key,
    )
    if not all(required):
        raise ValueError("TikTok API and token encryption settings are required.")

    database = Database(settings.database_url)
    cipher = TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    try:
        timezone_name, access_token, shop_cipher = await _resolve_shop(
            database, cipher, args.shop_id, args.shop_name
        )
        reference_date = args.reference_date or _completed_date(timezone_name)
        calendar_date.fromisoformat(reference_date)
        transport = TikTokTransport(
            base_url=_base_url(settings.tiktok_shop_identity_url),
            app_key=settings.tiktok_app_key,
            app_secret=settings.tiktok_app_secret.get_secret_value(),
            timeout_seconds=settings.tiktok_request_timeout_seconds,
            max_retries=settings.tiktok_request_max_retries,
            retry_base_seconds=settings.tiktok_retry_base_seconds,
            max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
        )
        probe = TikTokBestsellerProbe(transport)
        return await probe.run(
            access_token=access_token,
            shop_cipher=shop_cipher,
            date=reference_date,
            time_slot=args.time_slot,
            currency=args.currency,
            author_type=args.author_type,
        )
    finally:
        await database.dispose()


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
