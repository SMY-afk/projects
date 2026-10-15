from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

from app.parsers.affiliate_creator_export_parser import read_first_worksheet


class AffiliateVideoExportParseError(ValueError):
    pass


_MISSING = {"", "-", "--", "n/a", "na", "null"}
_REQUIRED_HEADERS = {
    "视频 ID",
    "联盟视频归因 GMV",
    "归因于视频的订单数",
    "视频商品曝光次数",
    "视频商品点击量",
    "视频播放量",
}
_MONEY_FIELDS = {
    "联盟视频归因 GMV": "gmvMinor",
    "平均订单金额": "averageOrderValueMinor",
    "退款金额": "refundedGmvMinor",
    "视频千次曝光成交金额": "distinctGpmMinor",
    "每位客户的平均 GMV": "averageGmvPerBuyerMinor",
    "预计佣金": "estimatedCommissionMinor",
}
_COUNT_FIELDS = {
    "归因于视频的订单数": "orderCount",
    "视频归因成交件数": "itemsSold",
    "已退款的商品件数": "refundedItems",
    "点赞数": "likes",
    "评论数": "comments",
    "分享次数": "shares",
    "视频商品曝光次数": "productImpressions",
    "视频商品点击量": "productClicks",
    "视频播放量": "views",
}
_RATE_FIELDS = {
    "完播率": "finishRate",
    "商品点击率": "productClickThroughRate",
    "互动率": "engagementRate",
}
_ENGLISH_HEADERS = {
    "Video title": "视频标题",
    "Video ID": "视频 ID",
    "Post date": "发布日期",
    "Video link": "视频链接",
    "Creator name": "达人名称",
    "Product ID": "商品 ID",
    "Creator video-attributed GMV": "联盟视频归因 GMV",
    "Video-attributed orders": "归因于视频的订单数",
    "AOV": "平均订单金额",
    "Video-attributed items sold": "视频归因成交件数",
    "Refunds": "退款金额",
    "Items refunded": "已退款的商品件数",
    "Likes": "点赞数",
    "Comments": "评论数",
    "Shares": "分享次数",
    "Video product impressions": "视频商品曝光次数",
    "Video product clicks": "视频商品点击量",
    "Completion rate": "完播率",
    "Video views": "视频播放量",
    "CTR": "商品点击率",
    "Video GPM": "视频千次曝光成交金额",
    "Engagement": "互动率",
    "Avg. GMV per customer": "每位客户的平均 GMV",
    "Est. commission": "预计佣金",
}


def parse_affiliate_video_export(
    content: bytes,
    currency: str,
    shop_timezone: str,
) -> list[dict[str, object]]:
    if not isinstance(content, bytes) or not content.startswith(b"PK\x03\x04"):
        raise AffiliateVideoExportParseError("Video export must be XLSX bytes")
    currency_code = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency_code):
        raise AffiliateVideoExportParseError("Currency must be a 3-letter code")
    try:
        timezone = ZoneInfo(shop_timezone)
        table = read_first_worksheet(content)
        headers = [
            _ENGLISH_HEADERS.get(str(value or "").strip(), str(value or "").strip())
            for value in next(table)
        ]
    except (StopIteration, OSError, ValueError) as error:
        raise AffiliateVideoExportParseError("Video export is invalid") from error
    missing = _REQUIRED_HEADERS - set(headers)
    if missing:
        raise AffiliateVideoExportParseError(
            "Video export is missing headers: " + ", ".join(sorted(missing))
        )
    result = []
    for row_number, values in enumerate(table, start=2):
        row = dict(zip(headers, values, strict=False))
        video_id = _text(row.get("视频 ID"))
        if not video_id or not video_id.isdecimal():
            continue
        result.append(_canonical_row(row, video_id, currency_code, timezone, row_number))
    return result


def _canonical_row(
    row: Mapping[str, object],
    video_id: str,
    currency: str,
    timezone: ZoneInfo,
    row_number: int,
) -> dict[str, object]:
    video_url = _text(row.get("视频链接"))
    result: dict[str, object] = {
        "videoId": video_id,
        "currency": currency,
        "title": _text(row.get("视频标题")),
        "creatorUsername": _creator_username(video_url),
        "creatorNickname": _text(row.get("达人名称")),
        "videoPostTime": _timestamp(row.get("发布日期"), timezone, row_number),
        "promotedProductIds": _identifiers(row.get("商品 ID")),
    }
    for header, field in _MONEY_FIELDS.items():
        result[field] = _money_minor(row.get(header), header, row_number)
    for header, field in _COUNT_FIELDS.items():
        result[field] = _count(row.get(header), header, row_number)
    for header, field in _RATE_FIELDS.items():
        result[field] = _rate(row.get(header), header, row_number)
    if video_url:
        result["sourceExtensions"] = {"videoUrl": video_url}
    return result


def _creator_username(video_url: str | None) -> str | None:
    if not video_url:
        return None
    parsed = urlsplit(video_url)
    hostname = (parsed.hostname or "").casefold()
    if hostname != "tiktok.com" and not hostname.endswith(".tiktok.com"):
        return None
    match = re.match(r"^/@([^/]+)/video/\d+(?:/|$)", parsed.path)
    if match is None:
        return None
    username = unquote(match.group(1)).strip().lstrip("@").strip()
    return username or None


def _timestamp(value: object, timezone: ZoneInfo, row: int) -> str | None:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return None
    for pattern in ("%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=timezone).isoformat()
        except ValueError:
            continue
    raise AffiliateVideoExportParseError(f"Row {row} has invalid post time")


def _identifiers(value: object) -> list[str]:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return []
    return list(dict.fromkeys(part for part in re.split(r"[,;\s]+", raw) if part))


def _money_minor(value: object, field: str, row: int) -> int | None:
    number = _number(value, field, row)
    if number is None:
        return None
    return int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _count(value: object, field: str, row: int) -> int | None:
    number = _number(value, field, row)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise AffiliateVideoExportParseError(f"Row {row} {field} is fractional")
    return int(number)


def _rate(value: object, field: str, row: int) -> str | None:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return None
    percent = raw.endswith("%")
    number = _number(raw[:-1] if percent else raw, field, row)
    assert number is not None
    ratio = number / 100 if percent or number > 1 else number
    return format(ratio.normalize(), "f")


def _number(value: object, field: str, row: int) -> Decimal | None:
    raw = _text(value)
    if raw is None or raw.casefold() in _MISSING:
        return None
    cleaned = re.sub(r"[$€£¥,\s]", "", raw)
    multiplier = Decimal(1)
    if cleaned[-1:].casefold() in {"k", "m", "b"}:
        multiplier = {
            "k": Decimal(1_000),
            "m": Decimal(1_000_000),
            "b": Decimal(1_000_000_000),
        }[cleaned[-1].casefold()]
        cleaned = cleaned[:-1]
    try:
        number = Decimal(cleaned) * multiplier
    except (InvalidOperation, ValueError) as error:
        raise AffiliateVideoExportParseError(
            f"Row {row} {field} is not numeric"
        ) from error
    if not number.is_finite() or number < 0:
        raise AffiliateVideoExportParseError(f"Row {row} {field} must be non-negative")
    return number


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None
