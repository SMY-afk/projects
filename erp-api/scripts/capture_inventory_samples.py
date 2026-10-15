from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import and_, select

from erp_api.core.config import Settings, get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.product import Product
from erp_api.models.product_sku import ProductSku
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_transport import TikTokRequest, TikTokTransport
from erp_api.services.token_cipher import TokenCipher


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture sanitized inventory samples.")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--days", type=int, default=365)
    return parser.parse_args()


def _base_url(endpoint: str | None) -> str:
    parsed = urlsplit(endpoint or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TikTok API endpoint is not configured correctly.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _credentials(settings: Settings, profile: str) -> tuple[str, str]:
    if profile == "legacy" and settings.tiktok_app_key and settings.tiktok_app_secret:
        return settings.tiktok_app_key, settings.tiktok_app_secret.get_secret_value()
    if (
        profile == "301"
        and settings.tiktok_301_app_key
        and settings.tiktok_301_app_secret
    ):
        return (
            settings.tiktok_301_app_key,
            settings.tiktok_301_app_secret.get_secret_value(),
        )
    raise ValueError("TikTok app profile is not configured.")


def _transport(settings: Settings, profile: str) -> TikTokTransport:
    app_key, app_secret = _credentials(settings, profile)
    return TikTokTransport(
        base_url=_base_url(settings.tiktok_shop_identity_url),
        app_key=app_key,
        app_secret=app_secret,
        timeout_seconds=settings.tiktok_request_timeout_seconds,
        max_retries=settings.tiktok_request_max_retries,
        retry_base_seconds=settings.tiktok_retry_base_seconds,
        max_retry_delay_seconds=settings.tiktok_max_retry_delay_seconds,
    )


def _data(payload: dict[str, object]) -> dict[str, object]:
    value = payload.get("data")
    return value if isinstance(value, dict) else {}


def _items(data: dict[str, object], key: str) -> list[dict[str, object]]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _quantity(value: object) -> int:
    text = str(value)
    return (
        int(text) if isinstance(value, (int, str)) and text.lstrip("-").isdigit() else 0
    )


def _iso_time(value: object) -> str | None:
    seconds = _quantity(value)
    return datetime.fromtimestamp(seconds, UTC).isoformat() if seconds else None


def _warehouse_sample(item: dict[str, object]) -> dict[str, object]:
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    return {
        "warehouseId": item.get("id"),
        "name": item.get("name"),
        "type": item.get("type"),
        "subType": item.get("sub_type"),
        "status": item.get("effect_status"),
        "isDefault": item.get("is_default"),
        "location": {
            "region": address.get("region"),
            "state": address.get("state"),
            "city": address.get("city"),
            "district": address.get("district"),
            "postalCode": address.get("postal_code"),
        },
    }


def _inventory_sample(item: dict[str, object]) -> dict[str, object]:
    goods = item.get("goods") if isinstance(item.get("goods"), dict) else {}
    detail = (
        item.get("on_hand_detail")
        if isinstance(item.get("on_hand_detail"), dict)
        else {}
    )
    skus = goods.get("skus") if isinstance(goods.get("skus"), list) else []
    sku_ids = [
        str(sku["id"]) for sku in skus if isinstance(sku, dict) and sku.get("id")
    ]
    return {
        "fbtWarehouseId": item.get("fbt_warehouse_id"),
        "goodsId": goods.get("id"),
        "referenceCode": goods.get("reference_code"),
        "platformSkuIds": sku_ids,
        "available": _quantity(detail.get("available_quantity")),
        "reserved": _quantity(detail.get("reserved_quantity")),
        "total": _quantity(detail.get("total_quantity")),
        "unfulfillable": _quantity(detail.get("unfulfillable_quantity")),
        "inTransit": _quantity(item.get("in_transit_quantity")),
    }


def _record_sample(item: dict[str, object]) -> dict[str, object]:
    goods = item.get("goods") if isinstance(item.get("goods"), dict) else {}
    order = item.get("order") if isinstance(item.get("order"), dict) else {}
    return {
        "createdAtUtc": _iso_time(item.get("create_time")),
        "fbtWarehouseId": item.get("fbt_warehouse_id"),
        "goodsId": goods.get("id"),
        "referenceCode": goods.get("reference_code"),
        "inventoryGoodsType": item.get("inventory_goods_type"),
        "recordType": order.get("type"),
        "orderId": order.get("id"),
        "initial": _quantity(item.get("initial_on_hand_quantity")),
        "changed": _quantity(item.get("changed_quantity")),
        "final": _quantity(item.get("final_on_hand_quantity")),
    }


async def _request(
    transport: TikTokTransport,
    request: TikTokRequest,
    *,
    token: str,
    tenant_id: UUID,
    shop_id: UUID,
) -> tuple[dict[str, object], str | None]:
    response = await transport.request_with_metadata(
        request,
        access_token=token,
        tenant_id=str(tenant_id),
        shop_id=str(shop_id),
    )
    return _data(response.payload), response.platform_request_id


async def _run(args: argparse.Namespace) -> dict[str, object]:
    settings = get_settings()
    if not settings.tiktok_token_encryption_key:
        raise ValueError("TikTok token encryption is not configured.")
    database = Database(settings.database_url)
    cipher = TokenCipher(settings.tiktok_token_encryption_key.get_secret_value())
    now = datetime.now(UTC)
    try:
        async with database.system_session_factory() as session:
            row = (
                await session.execute(
                    select(Shop, ShopConnection)
                    .join(
                        ShopConnection,
                        and_(
                            ShopConnection.shop_id == Shop.id,
                            ShopConnection.tenant_id == Shop.tenant_id,
                        ),
                    )
                    .where(Shop.id == args.shop_id, Shop.tenant_id == args.tenant_id)
                )
            ).one()
            shop, connection = row
            if connection.auth_status != "authorized":
                raise ValueError("Shop connection is not authorized.")
            if not connection.access_token_ciphertext or not connection.shop_ciphertext:
                raise ValueError("Shop connection material is missing.")
            transport = _transport(settings, connection.app_profile)
            token = cipher.decrypt(connection.access_token_ciphertext)
            shop_cipher = cipher.decrypt(connection.shop_ciphertext)
            common = {"shop_cipher": shop_cipher, "page_size": "100"}
            warehouses, warehouse_request_id = await _request(
                transport,
                TikTokRequest(
                    method="GET",
                    path="/logistics/202309/warehouses",
                    query={"shop_cipher": shop_cipher},
                ),
                token=token,
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
            )
            inventory, inventory_request_id = await _request(
                transport,
                TikTokRequest(
                    method="POST",
                    path="/fbt/202408/inventory/search",
                    query=common,
                    json_body={},
                ),
                token=token,
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
            )
            records, records_request_id = await _request(
                transport,
                TikTokRequest(
                    method="POST",
                    path="/fbt/202410/inventory_records/search",
                    query=common,
                    json_body={
                        "create_time_ge": int(
                            (now - timedelta(days=args.days)).timestamp()
                        ),
                        "create_time_le": int(now.timestamp()),
                    },
                ),
                token=token,
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
            )
            inventory_rows = [
                _inventory_sample(item) for item in _items(inventory, "inventory")
            ]
            record_rows = _items(records, "inventory_records")
            positive = [
                row for row in record_rows if _quantity(row.get("changed_quantity")) > 0
            ][:1]
            record_samples = record_rows[:8] + [
                row for row in positive if row not in record_rows[:8]
            ]
            sku_ids = {
                sku_id for item in inventory_rows for sku_id in item["platformSkuIds"]
            }
            mappings = (
                await session.execute(
                    select(ProductSku, Product)
                    .join(
                        Product,
                        and_(
                            Product.id == ProductSku.product_id,
                            Product.tenant_id == ProductSku.tenant_id,
                        ),
                    )
                    .where(
                        Product.tenant_id == args.tenant_id,
                        Product.shop_id == args.shop_id,
                        ProductSku.platform_sku_id.in_(sku_ids),
                    )
                )
            ).all()
        mapped_ids = {sku.platform_sku_id for sku, _ in mappings}
        return {
            "capturedAtUtc": now.isoformat(),
            "mode": "live_read_only_sanitized",
            "shop": {
                "tenantId": str(shop.tenant_id),
                "shopId": str(shop.id),
                "shopName": shop.shop_name,
                "region": shop.region,
                "appProfile": connection.app_profile,
            },
            "sellerWarehouses": {
                "total": len(_items(warehouses, "warehouses")),
                "samples": [
                    _warehouse_sample(item)
                    for item in sorted(
                        _items(warehouses, "warehouses"),
                        key=lambda value: not bool(value.get("is_default")),
                    )[:6]
                ],
                "requestId": warehouse_request_id,
            },
            "fbtInventory": {
                "total": inventory.get("total_count"),
                "samples": inventory_rows,
                "requestId": inventory_request_id,
            },
            "skuMappings": {
                "sourceSkuCount": len(sku_ids),
                "matchedCount": len(mapped_ids),
                "missingPlatformSkuIds": sorted(sku_ids - mapped_ids),
                "matched": [
                    {
                        "platformSkuId": sku.platform_sku_id,
                        "erpSkuName": sku.name,
                        "erpSnapshotStock": sku.stock,
                        "platformProductId": product.platform_product_id,
                    }
                    for sku, product in mappings
                ],
            },
            "fbtInventoryRecords": {
                "windowDays": args.days,
                "total": records.get("total_count"),
                "hasMore": bool(records.get("next_page_token")),
                "samples": [
                    _record_sample(item) for item in record_samples if item is not None
                ],
                "requestId": records_request_id,
            },
        }
    finally:
        await database.dispose()


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(
            f"{type(error).__name__}: inventory sample capture failed"
        ) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
