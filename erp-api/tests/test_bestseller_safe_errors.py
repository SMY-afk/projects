import pytest

from erp_api.routers.bestsellers import _read_error


@pytest.mark.parametrize(
    "category",
    [
        "data_unavailable",
        "reauthorization_required",
        "not_authorized",
        "rate_limited",
        "timeout",
        "platform_error",
        "sync_failed",
    ],
)
def test_known_bestseller_error_categories_are_preserved(category: str) -> None:
    assert _read_error(category).code == category


def test_unknown_error_category_is_not_exposed() -> None:
    unsafe = "upstream said token=secret"

    error = _read_error(unsafe)

    assert error.code == "sync_failed"
    assert unsafe not in error.message
