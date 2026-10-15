from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, select

from erp_api.core.config import Settings, get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRequest,
    TikTokTransport,
)
from erp_api.services.token_cipher import TokenCipher

SELLER_WAREHOUSE_SCOPE = "seller.logistics"
FBT_INFO_SCOPE = "seller.fbt.info"
INVENTORY_WRITE_SCOPE = "seller.product.write"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit inventory Gate 0 with read-only TikTok Shop probes."
    )
    parser.add_argument("--shop-id", type=UUID)
    parser.add_argument(
        "--scope-only",
        action="store_true",
        help="Read recorded OAuth scopes without calling TikTok Shop.",
    )
    return parser.parse_args()


def _base_url(endpoint: str | None) -> str:
    parsed = urlsplit(endpoint or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok API endpoint is not configured correctly.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _credentials(settings: Settings, app_profile: str) -> tuple[str, str] | None:
    if app_profile == "legacy":
        if not settings.tiktok_app_key or not settings.tiktok_app_secret:
            return None
        return settings.tiktok_app_key, settings.tiktok_app_secret.get_secret_value()
    if app_profile == "301":
        if not settings.tiktok_301_app_key or not settings.tiktok_301_app_secret:
            return None
        return (
            settings.tiktok_301_app_key,
            settings.tiktok_301_app_secret.get_secret_value(),
        )
    return None


def _transport(settings: Settings, app_profile: str) -> TikTokTransport | None:
    credentials = _credentials(settings, app_profile)
    if credentials is None:
        return None
    app_key, app_secret = credentials
    return TikTokTransport(
        base_url=_base_url(settings.tiktok_shop_identity_url),
        app_key=app_key,
        app_secret=app_secret,
        timeout_seconds=settings.tiktok_request_timeout_seconds,
        max_retries=settings.tiktok_request_max_retries,
        retry_base_seconds=settings.tiktok_retry_base_seconds,
        max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
    )


def _token_state(connection: ShopConnection) -> str:
    if not connection.access_token_ciphertext:
        return "missing"
    if connection.expires_at is None:
        return "unknown_expiry"
    expires_at = connection.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return "expired" if expires_at <= datetime.now(UTC) else "valid"


def _scope_evidence(scopes: object) -> dict[str, bool]:
    granted = set(scopes) if isinstance(scopes, list) else set()
    return {
        SELLER_WAREHOUSE_SCOPE: SELLER_WAREHOUSE_SCOPE in granted,
        FBT_INFO_SCOPE: FBT_INFO_SCOPE in granted,
        INVENTORY_WRITE_SCOPE: INVENTORY_WRITE_SCOPE in granted,
    }


def _list_value(payload: dict[str, object], key: str) -> list[object]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    return value if isinstance(value, list) else []


def _safe_failure(error: Exception) -> dict[str, object]:
    if isinstance(error, TikTokApiError):
        return {
            "status": "rejected",
            "errorType": type(error).__name__,
            "platformCode": error.code,
            "upstreamStatus": error.upstream_status_code,
            "requestId": error.request_id,
        }
    if isinstance(error, TikTokClientError):
        return {"status": "failed", "errorType": type(error).__name__}
    return {"status": "failed", "errorType": type(error).__name__}


async def _probe_seller_warehouses(
    transport: TikTokTransport,
    *,
    access_token: str,
    shop_cipher: str,
    tenant_id: UUID,
    shop_id: UUID,
) -> dict[str, object]:
    try:
        response = await transport.request_with_metadata(
            TikTokRequest(
                method="GET",
                path="/logistics/202309/warehouses",
                query={"shop_cipher": shop_cipher},
            ),
            access_token=access_token,
            tenant_id=str(tenant_id),
            shop_id=str(shop_id),
        )
    except Exception as error:  # noqa: BLE001 - emit a sanitized audit result
        return _safe_failure(error)
    warehouses = _list_value(response.payload, "warehouses")
    return {
        "status": "confirmed",
        "warehouseCount": len(warehouses),
        "requestId": response.platform_request_id,
    }


async def _probe_fbt_onboarding(
    transport: TikTokTransport,
    *,
    access_token: str,
    shop_cipher: str,
    tenant_id: UUID,
    shop_id: UUID,
) -> dict[str, object]:
    try:
        response = await transport.request_with_metadata(
            TikTokRequest(
                method="GET",
                path="/fbt/202409/merchants/onboarded_regions",
                query={"shop_cipher": shop_cipher},
            ),
            access_token=access_token,
            tenant_id=str(tenant_id),
            shop_id=str(shop_id),
        )
    except Exception as error:  # noqa: BLE001 - emit a sanitized audit result
        return _safe_failure(error)
    regions = _list_value(response.payload, "onboarded_regions")
    region_codes = sorted(
        {
            str(item.get("region_code")).strip()
            for item in regions
            if isinstance(item, dict) and item.get("region_code")
        }
    )
    return {
        "status": "onboarded" if region_codes else "not_onboarded",
        "regions": region_codes,
        "requestId": response.platform_request_id,
    }


async def _audit_shop(
    settings: Settings,
    cipher: TokenCipher,
    shop: Shop,
    connection: ShopConnection,
    *,
    scope_only: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "shopId": str(shop.id),
        "shopName": shop.shop_name,
        "region": shop.region,
        "tenantId": str(shop.tenant_id),
        "connectionStatus": connection.auth_status,
        "appProfile": connection.app_profile,
        "tokenState": _token_state(connection),
        "scopeEvidence": _scope_evidence(connection.scopes),
    }
    if scope_only:
        return result
    transport = _transport(settings, connection.app_profile)
    if transport is None:
        result["sellerWarehouse"] = {"status": "app_profile_not_configured"}
        result["fbt"] = {"status": "app_profile_not_configured"}
        return result
    if connection.auth_status != "authorized":
        result["sellerWarehouse"] = {"status": "connection_not_authorized"}
        result["fbt"] = {"status": "connection_not_authorized"}
        return result
    if not connection.access_token_ciphertext or not connection.shop_ciphertext:
        result["sellerWarehouse"] = {"status": "connection_material_missing"}
        result["fbt"] = {"status": "connection_material_missing"}
        return result
    access_token = cipher.decrypt(connection.access_token_ciphertext)
    shop_cipher = cipher.decrypt(connection.shop_ciphertext)
    result["sellerWarehouse"] = await _probe_seller_warehouses(
        transport,
        access_token=access_token,
        shop_cipher=shop_cipher,
        tenant_id=shop.tenant_id,
        shop_id=shop.id,
    )
    result["fbt"] = await _probe_fbt_onboarding(
        transport,
        access_token=access_token,
        shop_cipher=shop_cipher,
        tenant_id=shop.tenant_id,
        shop_id=shop.id,
    )
    return result


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if not settings.tiktok_token_encryption_key:
        raise ValueError("TikTok token encryption is not configured.")
    database = Database(settings.database_url)
    cipher = TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    try:
        async with database.system_session_factory() as session:
            statement = (
                select(Shop, ShopConnection)
                .join(
                    ShopConnection,
                    and_(
                        ShopConnection.shop_id == Shop.id,
                        ShopConnection.tenant_id == Shop.tenant_id,
                    ),
                )
                .where(Shop.platform == "tiktok", Shop.status == "active")
                .order_by(Shop.shop_name, Shop.id)
            )
            if args.shop_id is not None:
                statement = statement.where(Shop.id == args.shop_id)
            rows = (await session.execute(statement)).all()
        shops = [
            await _audit_shop(
                settings, cipher, shop, connection, scope_only=args.scope_only
            )
            for shop, connection in rows
        ]
        return {
            "auditedAt": datetime.now(UTC).isoformat(),
            "mode": "scope_only" if args.scope_only else "live_read_only",
            "shopCount": len(shops),
            "shops": shops,
        }
    finally:
        await database.dispose()


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(
            f"{type(error).__name__}: inventory Gate 0 audit failed"
        ) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
