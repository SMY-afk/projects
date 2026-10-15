from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.parsers.affiliate_creator_export_us_fields import (
    US_COUNT_FIELDS,
    US_MONEY_FIELDS,
    US_REQUIRED_HEADERS,
)
from app.parsers.xlsx_worksheet_reader import read_first_worksheet as _read_worksheet


class AffiliateCreatorExportParseError(ValueError):
    """Raised when a TikTok Affiliate Center creator export is unsafe or invalid."""


MAX_EXPORT_BYTES = 25 * 1024 * 1024
MAX_EXPORT_ROWS = 200_000
_MISSING = {"", "-", "--", "n/a", "na", "null"}
_REQUIRED_HEADERS = {
    "达人用户名",
    "联盟 GMV",
    "预计佣金",
    "成交件数",
    "联盟订单量",
    "点击率",
}
_MONEY_FIELDS = {
    "联盟 GMV": "affiliateGmvMinor",
    "联盟直播 GMV": "affiliateLiveGmvMinor",
    "联盟带货视频 GMV": "affiliateVideoGmvMinor",
    "联盟商品橱窗 GMV": "affiliateShowcaseGmvMinor",
    "预计佣金": "estimatedCommissionMinor",
    "预计固定费用": "estimatedFlatFeeMinor",
    "平均订单金额": "averageOrderAmountMinor",
    "定向合作 GMV": "targetCollaborationGmvMinor",
    "定向合作预计佣金": "targetCollaborationEstimatedCommissionMinor",
    "公开合作 GMV": "openCollaborationGmvMinor",
    "公开合作预计佣金": "openCollaborationEstimatedCommissionMinor",
    "联盟已退款的 GMV": "refundedAffiliateGmvMinor",
}
_COUNT_FIELDS = {
    "联盟商品成交件数": "affiliateProductItemsSold",
    "成交件数": "itemsSold",
    "联盟橱窗商品数": "showcaseProductCount",
    "联盟订单量": "affiliateOrderCount",
    "商品曝光次数": "productImpressions",
    "联盟直播数": "affiliateLiveCount",
    "联盟带货视频数": "affiliateVideoCount",
    "已退款的联盟商品数": "refundedAffiliateProductCount",
    "联盟粉丝数": "affiliateFollowerCount",
}
_DIRECT_FIELDS = {
    "点击率": "clickThroughRate",
    "平均联盟客户数": "averageAffiliateCustomers",
}
_KNOWN_HEADERS = (
    {"达人用户名"} | set(_MONEY_FIELDS) | set(_COUNT_FIELDS) | set(_DIRECT_FIELDS)
)


_COMPASS_REQUIRED_HEADERS = {
    "Creator name",
    "Creator-attributed GMV",
    "Est. commission",
    "Attributed orders",
}


def parse_affiliate_creator_export(
    content: bytes,
    currency: str,
) -> list[dict[str, object]]:
    if not isinstance(content, bytes) or not content.startswith(b"PK\x03\x04"):
        raise AffiliateCreatorExportParseError("Creator export must be XLSX bytes")
    if len(content) > MAX_EXPORT_BYTES:
        raise AffiliateCreatorExportParseError("Creator export exceeds size limit")
    currency_code = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency_code):
        raise AffiliateCreatorExportParseError("Currency must be a 3-letter code")
    table = read_first_worksheet(content)
    try:
        headers = [str(value or "").strip() for value in next(table)]
    except StopIteration as error:
        raise AffiliateCreatorExportParseError("Creator export is empty") from error
    compass_export = _COMPASS_REQUIRED_HEADERS.issubset(headers)
    us_export = US_REQUIRED_HEADERS.issubset(headers)
    missing = (set() if compass_export or us_export else _REQUIRED_HEADERS) - set(headers)
    if missing:
        raise AffiliateCreatorExportParseError(
            "Creator export is missing headers: " + ", ".join(sorted(missing))
        )
    result: list[dict[str, object]] = []
    for row_number, values in enumerate(table, start=2):
        row = dict(zip(headers, values, strict=False))
        if not any(_text(value) for value in row.values()):
            continue
        if compass_export and _is_compass_description_row(row):
            continue
        username = _text(
            row.get("Creator name")
            if compass_export
            else row.get("Creator username") or row.get("达人用户名")
        )
        if not username or username.casefold() in _MISSING:
            continue
        result.append(
            _compass_row(row, currency_code, row_number)
            if compass_export
            else _canonical_row(row, currency_code, row_number)
        )
        if len(result) > MAX_EXPORT_ROWS:
            raise AffiliateCreatorExportParseError("Creator export exceeds row limit")
    return result


def read_first_worksheet(content: bytes) -> Iterable[list[object | None]]:
    try:
        yield from _read_worksheet(content)
    except ValueError as error:
        raise AffiliateCreatorExportParseError(str(error)) from error


def _compass_row(
    row: Mapping[str, object], currency: str, row_number: int
) -> dict[str, object]:
    username = _text(row.get("Creator name"))
    if not username:
        raise AffiliateCreatorExportParseError(
            f"Row {row_number} has no creator username"
        )
    username = username if username.startswith("@") else f"@{username}"
    items_sold = _count(
        row.get("Creator-attributed items sold"),
        "Creator-attributed items sold",
        row_number,
    )
    parsed: dict[str, object] = {
        "username": username,
        "currency": currency,
        "affiliateGmvMinor": _money_minor(
            row.get("Creator-attributed GMV"), "Creator-attributed GMV", row_number
        ),
        "refundedAffiliateGmvMinor": _money_minor(
            row.get("Refunds"), "Refunds", row_number
        ),
        "estimatedCommissionMinor": _money_minor(
            row.get("Est. commission"), "Est. commission", row_number
        ),
        "affiliateOrderCount": _count(
            row.get("Attributed orders"), "Attributed orders", row_number
        ),
        "affiliateProductItemsSold": items_sold,
        "itemsSold": items_sold,
        "refundedAffiliateProductCount": _count(
            row.get("Items refunded"), "Items refunded", row_number
        ),
        "affiliateVideoCount": _count(row.get("Videos"), "Videos", row_number),
        "affiliateLiveCount": _count(
            row.get("LIVE streams"), "LIVE streams", row_number
        ),
        "averageOrderAmountMinor": _money_minor(
            row.get("AOV"), "AOV", row_number
        ),
    }
    samples = _count(row.get("Samples shipped"), "Samples shipped", row_number)
    if samples is not None:
        parsed["sourceExtensions"] = {"samplesShipped": samples}
    return parsed


def _is_compass_description_row(row: Mapping[str, object]) -> bool:
    value = _text(row.get("Creator-attributed GMV")) or ""
    return value.casefold().startswith("gmv generated by")


def _canonical_row(
    row: Mapping[str, object], currency: str, row_number: int
) -> dict[str, object]:
    username = _text(row.get("Creator username")) or _text(row.get("达人用户名"))
    if not username or username.casefold() in _MISSING:
        raise AffiliateCreatorExportParseError(
            f"Row {row_number} has no creator username"
        )
    username = username if username.startswith("@") else f"@{username}"
    parsed: dict[str, object] = {"username": username, "currency": currency}
    for header, field in (*_MONEY_FIELDS.items(), *US_MONEY_FIELDS.items()):
        if header in row:
            parsed[field] = _money_minor(row.get(header), header, row_number)
    for header, field in (*_COUNT_FIELDS.items(), *US_COUNT_FIELDS.items()):
        if header in row:
            parsed[field] = _count(row.get(header), header, row_number)
    rate_header = "CTR" if "CTR" in row else "点击率"
    parsed["clickThroughRate"] = _rate(row.get(rate_header), row_number)
    customer_header = (
        "Avg. affiliate customers"
        if "Avg. affiliate customers" in row
        else "平均联盟客户数"
    )
    if customer_header in row:
        parsed["averageAffiliateCustomers"] = _decimal_text(
            row.get(customer_header), customer_header, row_number
        )
    extensions = {
        header: value
        for header, value in row.items()
        if header
        and header not in (_KNOWN_HEADERS | set(US_MONEY_FIELDS) | set(US_COUNT_FIELDS))
        and header not in {"Creator username", "CTR", "Avg. affiliate customers"}
        and _text(value)
    }
    if extensions:
        parsed["sourceExtensions"] = extensions
    return parsed


def _money_minor(value: object, field: str, row: int) -> int | None:
    number = _number(value, field, row)
    if number is None:
        return None
    minor = (number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(minor)


def _count(value: object, field: str, row: int) -> int | None:
    number = _number(value, field, row)
    if number is None:
        return None
    integral = number.to_integral_value()
    if number != integral:
        raise AffiliateCreatorExportParseError(f"Row {row} {field} is fractional")
    return int(integral)


def _rate(value: object, row: int) -> str | None:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return None
    percent = raw.endswith("%")
    number = _number(raw[:-1] if percent else raw, "点击率", row)
    assert number is not None
    decimal = number / 100 if percent else number
    if not percent and decimal > 1:
        raise AffiliateCreatorExportParseError(f"Row {row} 点击率 exceeds 100%")
    return _plain_decimal(decimal)


def _decimal_text(value: object, field: str, row: int) -> str | None:
    number = _number(value, field, row)
    return _plain_decimal(number) if number is not None else None


def _number(value: object, field: str, row: int) -> Decimal | None:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return None
    cleaned = re.sub(r"[$€£¥,\s]", "", raw)
    multiplier = Decimal(1)
    if cleaned[-1:].casefold() in {"k", "m", "b"}:
        multiplier = {
            "k": Decimal(1000),
            "m": Decimal(1_000_000),
            "b": Decimal(1_000_000_000),
        }[cleaned[-1].casefold()]
        cleaned = cleaned[:-1]
    try:
        number = Decimal(cleaned) * multiplier
    except (InvalidOperation, ValueError) as error:
        raise AffiliateCreatorExportParseError(
            f"Row {row} {field} is not numeric"
        ) from error
    if not number.is_finite() or number < 0:
        raise AffiliateCreatorExportParseError(
            f"Row {row} {field} must be non-negative"
        )
    return number


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None


def _plain_decimal(value: Decimal) -> str:
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
