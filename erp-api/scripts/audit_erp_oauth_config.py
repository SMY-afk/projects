"""Compare required OAuth configuration presence without printing values."""

import io
import subprocess

from dotenv import dotenv_values
from pydantic import SecretStr

from erp_api.core.config import get_settings


NAMES = (
    "TIKTOK_APP_KEY",
    "TIKTOK_SERVICE_ID",
    "TIKTOK_APP_SECRET",
    "TIKTOK_AUTHORIZATION_URL",
    "TIKTOK_TOKEN_URL",
    "TIKTOK_SHOP_IDENTITY_URL",
    "TIKTOK_CALLBACK_BASE_URL",
    "TIKTOK_TOKEN_ENCRYPTION_KEY",
    "TIKTOK_WEBHOOK_SIGNING_SECRET",
    "ORDER_PII_ENCRYPTION_KEY",
)


def main() -> None:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "erp-ecs", "grep -E '^([A-Z0-9_]+)=' /etc/erp/erp-api.env"],
        capture_output=True,
        check=True,
        timeout=15,
    )
    remote = dotenv_values(stream=io.StringIO(result.stdout.decode()))
    settings = get_settings()
    for name in NAMES:
        value = getattr(settings, name.lower())
        local = value.get_secret_value() if isinstance(value, SecretStr) else value
        target = remote.get(name)
        print(
            f"{name} LOCAL={bool(local)} ECS={bool(target)} "
            f"MATCH={bool(local and target and str(local) == target)} "
            f"SINGLE_QUOTE={bool(local and chr(39) in str(local))} "
            f"BACKSLASH={bool(local and chr(92) in str(local))} "
            f"NEWLINE={bool(local and (chr(10) in str(local) or chr(13) in str(local)))}"
        )


if __name__ == "__main__":
    main()
