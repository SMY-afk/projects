from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from erp_api.services.tiktok_number_parser import (
    parse_tiktok_decimal,
    parse_tiktok_integer,
    parse_tiktok_money_minor,
    parse_tiktok_nonnegative_decimal,
    parse_tiktok_percent,
)


def pick(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in row:
            return row[name]
    return None


def unwrap(value: object) -> object:
    if isinstance(value, Mapping):
        return value.get("value")
    return value


def text(value: object, field: str, *, required: bool = False) -> str | None:
    value = unwrap(value)
    result = None if value is None else str(value).strip()
    if not result or result.casefold() in {"-", "--", "n/a", "na", "null", "none"}:
        if required:
            raise ValueError(f"{field}: required text is missing")
        return None
    return result


def creator_username_key(value: str) -> str:
    return value.strip().lstrip("@").casefold()


def creator_username_aliases(value: str) -> set[str]:
    key = creator_username_key(value)
    return {key, f"@{key}"}


def count(value: object, field: str) -> int | None:
    try:
        return parse_tiktok_integer(unwrap(value))
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def nonnegative_decimal(value: object, field: str) -> Decimal | None:
    try:
        return parse_tiktok_nonnegative_decimal(unwrap(value))
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def rate(value: object, field: str, *, allow_above_one: bool = False) -> str | None:
    try:
        raw = unwrap(value)
        if isinstance(raw, str) and not raw.strip().endswith("%"):  # DTO/API ratio
            parsed = parse_tiktok_nonnegative_decimal(raw)
            if parsed is not None and parsed > 1 and not allow_above_one:
                raise ValueError("ratio must be between 0 and 1")
        else:
            parsed = parse_tiktok_percent(raw)
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error
    return None if parsed is None else format(parsed.normalize(), "f")


def currency_code(value: object, expected: str, field: str = "currency") -> str:
    normalized_expected = expected.upper()
    if len(normalized_expected) != 3 or not normalized_expected.isalpha():
        raise ValueError(f"{field}: expected currency must be a three-letter code")
    actual = text(value, field) or expected
    normalized = actual.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError(f"{field}: currency must be a three-letter code")
    if normalized != normalized_expected:
        raise ValueError(
            f"{field}: payload currency {normalized} does not match {normalized_expected}"
        )
    return normalized


def major_money_minor(
    value: object, expected_currency: str, field: str
) -> tuple[int | None, str]:
    currency_value: object = expected_currency
    amount = value
    if isinstance(value, Mapping):
        amount = value.get("amount")
        currency_value = value.get("currency_code", value.get("currency"))
        if currency_value is None:
            raise ValueError(f"{field}.currency: required currency is missing")
    if isinstance(amount, float):
        raise TypeError(f"{field}: float money is forbidden")
    currency = currency_code(currency_value, expected_currency, f"{field}.currency")
    try:
        return parse_tiktok_money_minor(amount), currency
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error


def minor_money(value: object, field: str) -> int | None:
    raw = unwrap(value)
    if isinstance(raw, float):
        raise TypeError(f"{field}: float money is forbidden")
    try:
        number = parse_tiktok_decimal(raw)
    except ValueError as error:
        raise ValueError(f"{field}: {error}") from error
    if number is None:
        return None
    if number != number.to_integral_value():
        raise ValueError(f"{field}: minor amount must be an integer")
    return int(number)


def timestamp(value: object, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{field}: timezone is required")
        return value.astimezone(UTC)
    if isinstance(value, bool):
        raise TypeError(f"{field}: invalid timestamp")
    try:
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and value.isdigit()
        ):
            numeric = int(value)
            if numeric > 10_000_000_000:
                seconds, milliseconds = divmod(numeric, 1000)
                return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
                    milliseconds=milliseconds
                )
            return datetime.fromtimestamp(numeric, tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ValueError(f"{field}: invalid timestamp") from error
    raise ValueError(f"{field}: invalid timestamp")


def string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field}: expected a list")
    result = tuple(str(item).strip() for item in value if str(item).strip())
    if len(result) != len(set(result)):
        raise ValueError(f"{field}: duplicate values")
    return result


def image_url(value: object, field: str) -> str | None:
    if isinstance(value, Mapping):
        if not value:
            return None
        candidates = value.get("thumb_url_list")
        if not isinstance(candidates, list):
            raise TypeError(f"{field}: expected thumb_url_list")
        value = candidates[0] if candidates else None
    return text(value, field)
