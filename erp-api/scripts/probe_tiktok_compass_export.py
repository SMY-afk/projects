from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select

from app.parsers.affiliate_creator_export_parser import (
    parse_affiliate_creator_export,
    read_first_worksheet,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_compass_client import HttpTikTokCompassClient
from erp_api.services.tiktok_transport import TikTokTransport
from erp_api.services.token_cipher import TokenCipher


def _arguments():
    parser = argparse.ArgumentParser(
        description="Safely verify a TikTok Compass creator export."
    )
    parser.add_argument("--shop-name", required=True)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--days", type=int, choices=(1, 7, 30), default=1)
    parser.add_argument("--reuse-latest", action="store_true")
    parser.add_argument("--list-only", action="store_true")
    return parser.parse_args()


def _base_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok API endpoint is invalid.")
    return f"{parsed.scheme}://{parsed.netloc}"


async def _connection(database, token_cipher, shop_name):
    async with database.system_session_factory() as session:
        result = await session.execute(
            select(Shop, ShopConnection)
            .join(ShopConnection, ShopConnection.shop_id == Shop.id)
            .where(
                Shop.shop_name == shop_name,
                Shop.platform == "tiktok",
                Shop.status == "active",
                ShopConnection.auth_status == "authorized",
            )
        )
        matches = result.all()
    if len(matches) != 1:
        raise ValueError("Shop name must resolve to one authorized TikTok shop.")
    _shop, connection = matches[0]
    return (
        connection.app_profile,
        token_cipher.decrypt(connection.access_token_ciphertext),
        token_cipher.decrypt(connection.shop_ciphertext),
    )


def _credentials(settings, profile):
    if profile == "301":
        return (
            settings.tiktok_301_app_key,
            settings.tiktok_301_app_secret.get_secret_value()
            if settings.tiktok_301_app_secret
            else None,
        )
    return settings.tiktok_app_key, settings.tiktok_app_secret.get_secret_value()


async def _run(args):
    settings = get_settings()
    if not settings.tiktok_token_encryption_key:
        raise ValueError("TikTok token encryption key is not configured.")
    database = Database(settings.database_url)
    token_cipher = TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    try:
        profile, token, shop_cipher = await _connection(
            database, token_cipher, args.shop_name
        )
        app_key, app_secret = _credentials(settings, profile)
        if not app_key or not app_secret:
            raise ValueError("The shop App profile is not fully configured.")
        transport = TikTokTransport(
            base_url=_base_url(settings.tiktok_shop_identity_url),
            app_key=app_key,
            app_secret=app_secret,
            timeout_seconds=settings.tiktok_request_timeout_seconds,
            max_retries=settings.tiktok_request_max_retries,
            retry_base_seconds=settings.tiktok_retry_base_seconds,
            max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
        )
        client = HttpTikTokCompassClient(transport)
        if args.list_only:
            tasks = await client.list_creator_tasks(token, shop_cipher)
            return {
                "tasks": [
                    {
                        "status": task.get("status"),
                        "fileName": task.get("file_name"),
                    }
                    for task in tasks
                ]
            }
        selected_file_name = None
        if args.reuse_latest:
            tasks = await client.list_creator_tasks(token, shop_cipher)
            succeeded = [task for task in tasks if task.get("status") == "SUCCEEDED"]
            if not succeeded:
                raise ValueError("No completed Creator Compass task is available.")
            task = succeeded[0]
            task_id = task.get("id")
            if not isinstance(task_id, str):
                raise ValueError("Completed Creator Compass task has no ID.")
            selected_file_name = task.get("file_name")
            content = await client.download_task(token, shop_cipher, task_id)
        else:
            export = await client.export_creators(
                token,
                shop_cipher=shop_cipher,
                window_start=args.end_date - timedelta(days=args.days - 1),
                window_end=args.end_date,
            )
            content = export.content
        worksheet = iter(read_first_worksheet(content))
        headers = [str(value or "").strip() for value in next(worksheet)]
        samples = []
        for row in (next(worksheet, []), next(worksheet, [])):
            sample = list(row)
            if sample:
                sample[0] = "<redacted>"
            samples.append(sample)
        print(json.dumps({"headers": headers}, ensure_ascii=True, separators=(",", ":")))
        print(json.dumps({"samples": samples}, ensure_ascii=True, separators=(",", ":")))
        rows = parse_affiliate_creator_export(content, "USD")
        return {
            "status": "succeeded",
            "appProfile": profile,
            "recordCount": len(rows),
            "affiliateGmvMinor": sum(
                int(row.get("affiliateGmvMinor") or 0) for row in rows
            ),
            "estimatedCommissionMinor": sum(
                int(row.get("estimatedCommissionMinor") or 0) for row in rows
            ),
            "xlsxBytes": len(content),
            "fileName": selected_file_name,
        }
    finally:
        await database.dispose()


def main():
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
