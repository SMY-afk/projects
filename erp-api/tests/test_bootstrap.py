import pytest

from erp_api.bootstrap import (
    PERMISSION_NAMES,
    generate_admin_password,
    validate_admin_password,
)
from erp_api.core.permissions import MODULE_PERMISSION_CODES


def test_permission_names_cover_all_supported_permissions() -> None:
    assert set(PERMISSION_NAMES) == MODULE_PERMISSION_CODES


def test_generated_admin_password_is_strong() -> None:
    password = generate_admin_password()

    assert len(password) >= 20
    assert any(character.islower() for character in password)
    assert any(character.isupper() for character in password)
    assert any(character.isdigit() for character in password)


def test_short_admin_password_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 12 characters"):
        validate_admin_password("short")
