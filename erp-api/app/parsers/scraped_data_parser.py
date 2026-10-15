from collections.abc import Mapping

AFFILIATE_DATA_TYPE = "affiliate_order"
MAX_PLATFORM_ID_LENGTH = 100


class ScrapedDataParseError(ValueError):
    """Raised when a captured response cannot produce a stable raw record."""


def parse_scraped_data_response(
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    """Parse one captured Affiliate response into ScrapedData model values."""

    code = payload.get("code")
    if code not in (None, 0, "0"):
        raise ScrapedDataParseError(f"Affiliate response code is not zero: {code!r}")

    data = _mapping(payload.get("data"), field="data")
    raw_items = data.get("sku_order_list", [])
    if not isinstance(raw_items, list):
        raise ScrapedDataParseError("data.sku_order_list must be a list")

    parsed_items: list[dict[str, object]] = []
    for index, raw_item in enumerate(raw_items):
        try:
            item = _mapping(raw_item, field="sku_order_list item")
            parsed_items.append(parse_scraped_data_item(item))
        except ScrapedDataParseError as error:
            raise ScrapedDataParseError(
                f"Invalid data.sku_order_list[{index}]: {error}"
            ) from error
    return parsed_items


def parse_scraped_data_item(
    item: Mapping[str, object],
) -> dict[str, object]:
    """Parse one Affiliate SKU-order item without discarding its raw JSON."""

    base = _mapping(
        item.get("sku_order_base_info_for_affiliate_seller"),
        field="sku_order_base_info_for_affiliate_seller",
    )
    sku_order = _mapping(
        base.get("sku_order_info"),
        field="sku_order_base_info_for_affiliate_seller.sku_order_info",
    )
    creator = _optional_mapping(base.get("creator_info"))
    product = _optional_mapping(base.get("product_info"))

    main_order_id = _required_text(sku_order, "main_order_id")
    sku_id = _required_text(sku_order, "sku_id")
    platform_id = f"{AFFILIATE_DATA_TYPE}:{main_order_id}:{sku_id}"
    if len(platform_id) > MAX_PLATFORM_ID_LENGTH:
        raise ScrapedDataParseError(
            f"Generated platform_id exceeds {MAX_PLATFORM_ID_LENGTH} characters"
        )

    return {
        "platform_id": platform_id,
        "data_type": AFFILIATE_DATA_TYPE,
        "creator_id": (
            _optional_text(creator, "creator_id")
            or _optional_text(creator, "creator_oec_id")
        ),
        "creator_name": (
            _optional_text(creator, "creator_nickname")
            or _optional_text(creator, "creator_username")
        ),
        "title": _optional_text(product, "product_name"),
        "raw_data": dict(item),
    }


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScrapedDataParseError(f"{field} must be an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _required_text(value: Mapping[str, object], key: str) -> str:
    parsed = _optional_text(value, key)
    if parsed is None:
        raise ScrapedDataParseError(f"{key} is required")
    return parsed


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is None or isinstance(raw, (dict, list)):
        return None
    parsed = str(raw).strip()
    return parsed or None
