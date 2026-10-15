from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from erp_api.services.tiktok_transport import TikTokApiError


@dataclass(frozen=True)
class TikTokTokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scopes: list[str]
    open_id: str | None = None
    user_type: int | None = None
    refresh_expires_in: int | None = None
    region: str | None = None


@dataclass(frozen=True)
class TikTokShopIdentity:
    platform_shop_id: str
    name: str
    region: str | None
    shop_cipher: str | None = None


@dataclass(frozen=True)
class TikTokSku:
    platform_sku_id: str
    seller_sku: str | None
    price_amount: str | None
    currency: str | None
    inventory_quantity: int | None


@dataclass(frozen=True)
class TikTokProduct:
    platform_product_id: str
    name: str
    status: str | None
    create_time: int | None
    sales_regions: list[str]
    skus: list[TikTokSku]
    image_urls: list[str]


@dataclass(frozen=True)
class TikTokProductDetail(TikTokProduct):
    description: str | None
    category_chain: list[str]
    package_weight_value: str | None
    package_weight_unit: str | None
    package_dimensions: dict[str, str]
    brand: str | None
    raw_payload: dict[str, object]


@dataclass(frozen=True)
class TikTokProductPage:
    products: list[TikTokProduct]
    next_page_token: str
    total_count: int | None


def parse_token_response(payload: Mapping[str, Any]) -> TikTokTokenSet:
    data = _nested_data(payload)
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise TikTokApiError(
            "TikTok token response did not contain an access token.",
            code="invalid_token_response",
            status_code=502,
        )
    scopes = _scopes(
        data.get("scope", data.get("scopes", data.get("granted_scopes", [])))
    )
    expires_in = _integer_or_none(data.get("expires_in"))
    if expires_in is None:
        expires_at = _integer_or_none(data.get("access_token_expire_in"))
        expires_in = (
            max(0, expires_at - int(time.time())) if expires_at is not None else None
        )
    refresh_expires_in = _integer_or_none(data.get("refresh_expires_in"))
    if refresh_expires_in is None:
        refresh_expires_at = _integer_or_none(data.get("refresh_token_expire_in"))
        refresh_expires_in = (
            max(0, refresh_expires_at - int(time.time()))
            if refresh_expires_at is not None
            else None
        )
    return TikTokTokenSet(
        access_token=access_token,
        refresh_token=_optional_string(data.get("refresh_token")),
        expires_in=expires_in,
        scopes=scopes,
        open_id=_optional_string(data.get("open_id")),
        user_type=_integer_or_none(data.get("user_type")),
        refresh_expires_in=refresh_expires_in,
        region=_optional_string(
            data.get("creator_base_region", data.get("seller_base_region"))
        ),
    )


def parse_shop_identity_response(payload: Mapping[str, Any]) -> TikTokShopIdentity:
    data = _nested_data(payload)
    shops = data.get("shops")
    if isinstance(shops, list) and shops and isinstance(shops[0], Mapping):
        data = shops[0]
    platform_shop_id = _first_string(data, "shop_id", "shopId", "id")
    if not platform_shop_id:
        raise TikTokApiError(
            "TikTok shop response did not contain a shop identity.",
            code="invalid_shop_response",
            status_code=502,
        )
    name = (
        _first_string(data, "shop_name", "shopName", "name", "seller_name")
        or platform_shop_id
    )
    region = _first_string(data, "region", "seller_base_region")
    shop_cipher = _first_string(data, "shop_cipher", "shopCipher", "cipher")
    return TikTokShopIdentity(
        platform_shop_id=platform_shop_id,
        name=name,
        region=region,
        shop_cipher=shop_cipher,
    )


def parse_authorized_shops_response(
    payload: Mapping[str, Any],
) -> list[TikTokShopIdentity]:
    if not isinstance(payload, Mapping):
        raise TikTokApiError(
            "TikTok authorized shops response was not an object.",
            code="invalid_authorized_shops_response",
            status_code=502,
        )
    data = _nested_data(payload)
    raw_shops = data.get("shops")
    if not isinstance(raw_shops, list):
        raise TikTokApiError(
            "TikTok authorized shops response did not contain a shops list.",
            code="invalid_authorized_shops_response",
            status_code=502,
        )
    result: list[TikTokShopIdentity] = []
    for value in raw_shops:
        if not isinstance(value, Mapping):
            raise TikTokApiError(
                "TikTok authorized shops response contained an invalid shop.",
                code="invalid_authorized_shops_response",
                status_code=502,
            )
        shop_id = _first_string(value, "id", "shop_id", "shopId")
        cipher = _first_string(value, "cipher", "shop_cipher", "shopCipher")
        if not shop_id or not cipher:
            raise TikTokApiError(
                "TikTok authorized shop did not contain an ID and cipher.",
                code="invalid_authorized_shops_response",
                status_code=502,
            )
        result.append(
            TikTokShopIdentity(
                platform_shop_id=shop_id,
                name=_first_string(value, "name", "shop_name", "shopName") or shop_id,
                region=_first_string(value, "region", "seller_base_region"),
                shop_cipher=cipher,
            )
        )
    return result


def parse_product_page_response(payload: Mapping[str, Any]) -> TikTokProductPage:
    if not isinstance(payload, Mapping):
        raise TikTokApiError(
            "TikTok product response was not an object.",
            code="invalid_product_response",
            status_code=502,
        )
    data = _nested_data(payload)
    raw_products = data.get("products")
    if not isinstance(raw_products, list):
        raise TikTokApiError(
            "TikTok product response did not contain a products list.",
            code="invalid_product_response",
            status_code=502,
        )
    products = [_parse_product(item) for item in raw_products]
    next_page_token = data.get("next_page_token", "")
    if not isinstance(next_page_token, str):
        raise TikTokApiError(
            "TikTok product response contained an invalid page token.",
            code="invalid_product_response",
            status_code=502,
        )
    return TikTokProductPage(
        products=products,
        next_page_token=next_page_token,
        total_count=_integer_or_none(data.get("total_count")),
    )


def parse_product_detail_response(payload: Mapping[str, Any]) -> TikTokProductDetail:
    if not isinstance(payload, Mapping):
        raise TikTokApiError(
            "TikTok product detail response was not an object.",
            code="invalid_product_response",
            status_code=502,
        )
    data = _nested_data(payload)
    base = _parse_product(data)
    raw_images = (
        data.get("main_images") or data.get("images") or data.get("image_urls") or []
    )
    image_urls = _parse_image_urls(raw_images)
    raw_categories = data.get("category_chains", [])
    category_chain = [
        str(item.get("local_name"))
        for item in raw_categories
        if isinstance(item, Mapping) and item.get("local_name")
    ]
    weight = (
        data.get("package_weight")
        if isinstance(data.get("package_weight"), Mapping)
        else {}
    )
    dimensions = (
        data.get("package_dimensions")
        if isinstance(data.get("package_dimensions"), Mapping)
        else {}
    )
    brand = _first_string(data, "brand", "brand_name")
    if not brand:
        attributes = data.get("product_attributes", [])
        brand = next(
            (
                str(v.get("name"))
                for a in attributes
                if isinstance(a, Mapping) and "brand" in str(a.get("name", "")).lower()
                for v in (
                    a.get("values", []) if isinstance(a.get("values"), list) else []
                )
                if isinstance(v, Mapping) and v.get("name")
            ),
            None,
        )
    return TikTokProductDetail(
        **{**base.__dict__, "image_urls": image_urls},
        description=_optional_string(data.get("description")),
        category_chain=category_chain,
        package_weight_value=_optional_string(weight.get("value")),
        package_weight_unit=_optional_string(weight.get("unit")),
        package_dimensions={
            str(k): str(v) for k, v in dimensions.items() if v is not None
        },
        brand=brand,
        raw_payload=dict(data),
    )


def _parse_image_urls(raw_images: Any) -> list[str]:
    if not isinstance(raw_images, list):
        return []
    urls: list[str] = []
    for image in raw_images:
        if isinstance(image, str):
            urls.append(image)
        elif isinstance(image, Mapping):
            values = (
                image.get("urls") or image.get("url") or image.get("image_url") or []
            )
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                urls.extend(value for value in values if isinstance(value, str))
    return list(dict.fromkeys(urls))


def _parse_product(value: Any) -> TikTokProduct:
    if not isinstance(value, Mapping):
        raise TikTokApiError(
            "TikTok product response contained an invalid product.",
            code="invalid_product_response",
            status_code=502,
        )
    product_id = _first_string(value, "id", "product_id", "productId")
    if not product_id:
        raise TikTokApiError(
            "TikTok product response did not contain a product ID.",
            code="invalid_product_response",
            status_code=502,
        )
    raw_skus = value.get("skus", [])
    if not isinstance(raw_skus, list):
        raise TikTokApiError(
            "TikTok product response contained an invalid SKU list.",
            code="invalid_product_response",
            status_code=502,
        )
    audit = value.get("audit")
    audit_status = audit.get("status") if isinstance(audit, Mapping) else None
    raw_regions = value.get("sales_regions", value.get("sale_regions", []))
    regions = (
        [region for region in raw_regions if isinstance(region, str)]
        if isinstance(raw_regions, list)
        else []
    )
    return TikTokProduct(
        platform_product_id=product_id,
        name=_first_string(value, "title", "product_name", "name") or product_id,
        status=_first_string(value, "status")
        or (audit_status if isinstance(audit_status, str) else None),
        create_time=_integer_or_none(value.get("create_time")),
        sales_regions=regions,
        skus=[_parse_sku(sku) for sku in raw_skus],
        image_urls=_parse_image_urls(
            value.get("main_images")
            or value.get("images")
            or value.get("image_urls")
            or []
        ),
    )


def _parse_sku(value: Any) -> TikTokSku:
    if not isinstance(value, Mapping):
        raise TikTokApiError(
            "TikTok product response contained an invalid SKU.",
            code="invalid_product_response",
            status_code=502,
        )
    sku_id = _first_string(value, "id", "sku_id", "skuId")
    if not sku_id:
        raise TikTokApiError(
            "TikTok SKU response did not contain a SKU ID.",
            code="invalid_product_response",
            status_code=502,
        )
    price = value.get("price")
    price_map = price if isinstance(price, Mapping) else {}
    inventory = value.get("inventory")
    inventory_map = inventory if isinstance(inventory, Mapping) else {}
    amount = _first_value(price_map, "sale_price", "price", "amount")
    if amount is None:
        amount = _first_value(value, "sale_price", "price")
    amount_map = amount if isinstance(amount, Mapping) else {}
    if amount_map:
        amount = _first_value(amount_map, "amount", "value", "price")
    currency = (
        _first_string(price_map, "currency")
        or _first_string(amount_map, "currency")
        or _first_string(value, "currency")
    )
    if isinstance(inventory, list):
        quantity = sum(
            quantity
            for item in inventory
            if isinstance(item, Mapping)
            for quantity in [
                _integer_or_none(
                    _first_value(item, "quantity", "available_quantity", "stock")
                )
            ]
            if quantity is not None
        )
    else:
        quantity = _integer_or_none(
            _first_value(inventory_map, "quantity", "available_quantity", "stock")
            if inventory_map
            else _first_value(value, "inventory_quantity", "quantity", "stock")
        )
    return TikTokSku(
        platform_sku_id=sku_id,
        seller_sku=_first_string(value, "seller_sku", "sellerSku"),
        price_amount=None if amount is None else str(amount),
        currency=currency,
        inventory_quantity=quantity,
    )


def _nested_data(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, Mapping) else {}


def _first_string(data: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_value(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        return [scope.strip() for scope in value.split(",") if scope.strip()]
    if isinstance(value, list):
        return [scope for scope in value if isinstance(scope, str) and scope]
    return []
