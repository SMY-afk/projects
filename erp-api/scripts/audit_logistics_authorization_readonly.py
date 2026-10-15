"""Audit shop identity and official logistics without refreshing tokens or writing data."""

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from erp_api.core.config import Settings, get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import (
    _create_shop_repository,
    _create_tiktok_app_registry,
    _create_tiktok_client,
)
from erp_api.services.tiktok_transport import (
    TikTokClientError,
    TikTokRequest,
    TikTokTransport,
    tiktok_request_context,
)


async def audit(settings, shop_name=None):
    database = Database(settings.database_url)
    secrets = []
    captured = []
    original_parse = TikTokTransport._parse_response

    def capture_response(response, retry_after):
        try:
            payload = response.json()
            message = str(payload.get("message", ""))[:500]
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "[redacted]")
            captured.append(
                {
                    "httpStatus": response.status_code,
                    "code": payload.get("code"),
                    "message": message,
                    "requestId": payload.get("request_id"),
                }
            )
        except (ValueError, AttributeError):
            captured.append({"httpStatus": response.status_code})
        return original_parse(response, retry_after)

    TikTokTransport._parse_response = staticmethod(capture_response)
    try:
        shops = _create_shop_repository(settings, database)
        registry = _create_tiktok_app_registry(settings, shops)
        client = _create_tiktok_client(settings, registry)
        if shops is None or client is None or registry is None:
            raise RuntimeError("TikTok client configuration is incomplete.")
        secrets.extend(profile.app_key for profile in registry.profiles.values())
        secrets.extend(profile.app_secret for profile in registry.profiles.values())
        async with database.system_session_factory() as session:
            query = text("""
                SELECT s.id, s.tenant_id, s.shop_name, s.platform_shop_id,
                       c.auth_status, c.app_profile, c.expires_at, c.updated_at,
                       c.scopes,
                       (SELECT max(o.platform_updated_at) FROM orders o
                        WHERE o.shop_id=s.id AND o.tenant_id=s.tenant_id) AS latest_order_at
                FROM shops s LEFT JOIN shop_connections c ON c.shop_id=s.id
                WHERE s.platform='tiktok' AND s.status='active'
                  AND (CAST(:shop AS TEXT) IS NULL OR s.shop_name=:shop)
                ORDER BY s.shop_name
            """)
            rows = (await session.execute(query, {"shop": shop_name})).all()
            targets = []
            for shop in rows:
                order = (
                    await session.execute(
                        text("""
                    SELECT o.id, o.platform_order_id, o.external_status,
                           f.platform_package_id
                    FROM orders o JOIN order_fulfillments f ON f.order_id=o.id
                    WHERE o.shop_id=:shop AND o.tenant_id=:tenant
                      AND o.external_status IN
                          ('IN_TRANSIT','AWAITING_COLLECTION','DELIVERED','COMPLETED')
                      AND f.platform_package_id<>''
                    ORDER BY CASE WHEN o.external_status='IN_TRANSIT' THEN 0 ELSE 1 END,
                             o.platform_updated_at DESC LIMIT 1
                """),
                        {"shop": shop.id, "tenant": shop.tenant_id},
                    )
                ).first()
                targets.append((shop, order))
        results = []
        for shop, order in targets:
            record = {
                "shopId": str(shop.id),
                "shopName": shop.shop_name,
                "platformShopId": shop.platform_shop_id,
                "authStatus": shop.auth_status,
                "appProfile": shop.app_profile,
                "expiresAt": str(shop.expires_at),
                "connectionUpdatedAt": str(shop.updated_at),
                "latestOrderAt": str(shop.latest_order_at),
                "logisticsScope": "seller.logistics" in (shop.scopes or []),
                "tokenExpired": bool(
                    shop.expires_at and shop.expires_at <= datetime.now(UTC)
                ),
            }
            token = await shops.get_access_token(shop.tenant_id, shop.id)
            cipher = await shops.get_shop_cipher(shop.tenant_id, shop.id)
            secrets.extend([token, cipher])
            if not token or not cipher:
                record["error"] = "missing_authorized_credentials"
                results.append(record)
                continue
            with tiktok_request_context(
                tenant_id=str(shop.tenant_id), shop_id=str(shop.id)
            ):
                captured.clear()
                try:
                    identities = await client.get_authorized_shops(token)
                    matching = [
                        item
                        for item in identities
                        if item.platform_shop_id == shop.platform_shop_id
                    ]
                    record["identity"] = {
                        "ok": bool(matching),
                        "authorizedShopCount": len(identities),
                        "cipherMatches": bool(
                            matching and matching[0].shop_cipher == cipher
                        ),
                        "response": captured[-1] if captured else {},
                    }
                except (TikTokClientError, ValueError) as error:
                    record["identity"] = error_record(error, captured)
                if order is not None:
                    record["orderId"] = str(order.id)
                    record["orderSuffix"] = order.platform_order_id[-5:]
                    for name, path in [
                        (
                            "tracking",
                            f"/fulfillment/202309/orders/{order.platform_order_id}/tracking",
                        ),
                        (
                            "package",
                            f"/fulfillment/202309/packages/{order.platform_package_id}",
                        ),
                    ]:
                        captured.clear()
                        try:
                            payload = await client.api_transport.request(
                                TikTokRequest(
                                    "GET", path, query={"shop_cipher": cipher}
                                ),
                                access_token=token,
                            )
                            data = payload.get("data", {})
                            record[name] = {
                                "ok": True,
                                "response": captured[-1] if captured else {},
                                "eventCount": len(data.get("tracking", []))
                                if name == "tracking"
                                else None,
                                "packageStatus": data.get("package_status")
                                if name == "package"
                                else None,
                            }
                        except (TikTokClientError, ValueError) as error:
                            record[name] = error_record(error, captured)
                else:
                    record["error"] = "no_shipped_order_with_package"
            results.append(record)
        return {"checkedAt": datetime.now(UTC).isoformat(), "shops": results}
    finally:
        TikTokTransport._parse_response = staticmethod(original_parse)
        await database.dispose()


def error_record(error, captured):
    return {
        "ok": False,
        "errorType": type(error).__name__,
        "code": getattr(error, "code", None),
        "response": captured[-1] if captured else {},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--shop")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    settings = Settings(_env_file=args.env_file) if args.env_file else get_settings()
    result = asyncio.run(audit(settings, args.shop))
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
