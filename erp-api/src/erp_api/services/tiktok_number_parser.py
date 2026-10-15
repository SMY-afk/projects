from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation

NULL_MARKERS = frozenset({"", "-", "--", "—", "–", "n/a", "na", "null", "none"})
COMPACT_MULTIPLIERS = {
    "K": Decimal(1_000),
    "M": Decimal(1_000_000),
    "B": Decimal(1_000_000_000),
    "万": Decimal(10_000),
    "亿": Decimal(100_000_000),
}
NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?:[Ee][+-]?\d+)?$"
)


class TikTokNumberError(ValueError):
    pass


def parse_tiktok_decimal(value: object) -> Decimal | None:
    return _parse_number(value, allow_currency=False, allow_compact=False)


def parse_tiktok_nonnegative_decimal(value: object) -> Decimal | None:
    number = parse_tiktok_decimal(value)
    if number is not None and number < 0:
        raise TikTokNumberError("不能是负数。")
    return number


def parse_tiktok_integer(value: object) -> int | None:
    number = _parse_number(value, allow_currency=False, allow_compact=True)
    if number is None:
        return None
    if number < 0:
        raise TikTokNumberError("不能是负数。")
    if number != number.to_integral_value():
        raise TikTokNumberError("必须是整数。")
    return int(number)


def parse_tiktok_money_minor(value: object) -> int | None:
    amount = _parse_number(value, allow_currency=True, allow_compact=True)
    if amount is None:
        return None
    minor = amount * 100
    if minor != minor.to_integral_value():
        raise TikTokNumberError("金额最多只能有两位小数。")
    return int(minor)


def parse_tiktok_percent(value: object) -> Decimal | None:
    text = _normalize_text(value)
    if text is None:
        return None
    if isinstance(value, bool):
        raise TikTokNumberError("不是有效百分比。")
    if isinstance(value, (int, float, Decimal)):
        rate = _parse_number(value, allow_currency=False, allow_compact=False)
    else:
        if not text.endswith("%"):
            raise TikTokNumberError("必须带百分号。")
        rate = _parse_number(text[:-1], allow_currency=False, allow_compact=False)
        if rate is not None:
            rate /= Decimal(100)
    if rate is None:
        return None
    if rate < 0 or rate > 1:
        raise TikTokNumberError("百分比必须在 0% 到 100% 之间。")
    return rate


def _parse_number(
    value: object, *, allow_currency: bool, allow_compact: bool
) -> Decimal | None:
    text = _normalize_text(value)
    if text is None:
        return None
    if isinstance(value, bool):
        raise TikTokNumberError("不是有效数字。")
    if isinstance(value, float) and not math.isfinite(value):
        raise TikTokNumberError("不是有限数字。")

    negative_parentheses = text.startswith("(") and text.endswith(")")
    if "(" in text or ")" in text:
        if not negative_parentheses:
            raise TikTokNumberError("不是有效数字。")
        text = text[1:-1]
        if text.startswith(("+", "-")):
            raise TikTokNumberError("负号格式不明确。")

    if allow_currency:
        text = _strip_usd_token(text)
    elif any(token in text.upper() for token in ("$", "USD")):
        raise TikTokNumberError("该字段不能包含货币符号。")

    multiplier = Decimal(1)
    suffix = text[-1:].upper()
    if suffix in COMPACT_MULTIPLIERS:
        if not allow_compact:
            raise TikTokNumberError("该字段不能使用缩写单位。")
        multiplier = COMPACT_MULTIPLIERS[suffix]
        text = text[:-1]

    if not NUMBER_PATTERN.fullmatch(text):
        raise TikTokNumberError("不是有效数字。")
    try:
        number = Decimal(text.replace(",", "")) * multiplier
    except InvalidOperation as error:
        raise TikTokNumberError("不是有效数字。") from error
    return -number if negative_parentheses else number


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).replace("−", "-")
    text = re.sub(r"\s+", "", text).strip()
    return None if text.casefold() in NULL_MARKERS else text


def _strip_usd_token(text: str) -> str:
    upper = text.upper()
    matches = 0
    for token in ("US$", "USD", "$"):
        if upper.startswith(token):
            text = text[len(token) :]
            matches += 1
            break
    upper = text.upper()
    for token in ("USD", "US$"):
        if upper.endswith(token):
            text = text[: -len(token)]
            matches += 1
            break
    if matches > 1 or not text:
        raise TikTokNumberError("货币标记格式不明确。")
    return text
