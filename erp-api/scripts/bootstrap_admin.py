from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from erp_api.bootstrap import (
    bootstrap_admin,
    generate_admin_password,
    validate_admin_password,
)
from erp_api.core.config import get_settings


def _read_credentials(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _write_credentials(
    path: Path, *, tenant_name: str, username: str, password: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"tenant={tenant_name}\nusername={username}\npassword={password}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the ERP tenant and administrator account."
    )
    parser.add_argument(
        "--tenant-name",
        default=os.getenv("INITIAL_TENANT_NAME", "万矩环通科技有限公司"),
    )
    parser.add_argument(
        "--username", default=os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=Path("secrets/local-admin-credentials.txt"),
    )
    parser.add_argument("--reset-password", action="store_true")
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    password = os.getenv("INITIAL_ADMIN_PASSWORD")
    generated_password = False
    if password is None and args.credentials_file.is_file():
        credentials = _read_credentials(args.credentials_file)
        password = credentials.get("password")
    if password is None:
        password = generate_admin_password()
        generated_password = True
        _write_credentials(
            args.credentials_file,
            tenant_name=args.tenant_name,
            username=args.username,
            password=password,
        )
    validate_admin_password(password)

    result = await bootstrap_admin(
        get_settings().database_url,
        tenant_name=args.tenant_name,
        username=args.username,
        password=password,
        reset_password=args.reset_password,
    )
    credential_location = (
        str(args.credentials_file.resolve())
        if generated_password
        else "existing secure source"
    )
    print(
        "Bootstrap complete: "
        f"tenant_created={result.tenant_created}, "
        f"permissions_created={result.permissions_created}, "
        f"role_created={result.role_created}, "
        f"user_created={result.user_created}, "
        f"credentials={credential_location}"
    )


if __name__ == "__main__":
    asyncio.run(_run())
