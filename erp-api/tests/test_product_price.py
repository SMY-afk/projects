import pytest

from erp_api.services.product_repository import _price_minor, format_current_price


def test_current_price_formats_single_sku_price() -> None:
    assert (
        format_current_price([{"priceMinor": 1999, "currency": "USD"}]) == "USD 19.99"
    )


def test_current_price_formats_sku_price_range() -> None:
    skus = [
        {"priceMinor": 6800, "currency": "USD"},
        {"priceMinor": 20800, "currency": "USD"},
    ]

    assert format_current_price(skus) == "USD 68.00 - 208.00"


def test_current_price_ignores_missing_prices() -> None:
    assert format_current_price([{"priceMinor": 0, "currency": "USD"}]) is None


def test_stored_price_uses_decimal_half_up_rounding() -> None:
    assert _price_minor("19.995") == 2000
    assert _price_minor("0.005") == 1


def test_stored_price_rejects_invalid_values() -> None:
    assert _price_minor(None) == 0
    with pytest.raises(ValueError, match="SKU price is invalid"):
        _price_minor("invalid")
