"""Stage isolated daily-creator credentials without starting a worker."""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

API_ENV = Path("/etc/erp/erp-api.env")
SAMPLE_ENV = Path("/etc/erp/erp-sample-worker.env")
DAILY_ENV = Path("/etc/erp/erp-daily-valid-worker.env")
TENANT_ID = "6d0032eb-6a58-5a93-a819-d55c2a1c2e26"
BASE_TOKEN = "exampleb6b20e30bcdc75e12b5f"
TABLE_ID = "tblexamplef1d0cfa5"
RDS_HOST = "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"
EXPORT_URL = "http://api:8080/api/internal/affiliate-center/"


def _read(
    path: Path, *, allowed_duplicate: str | None = None
) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        if not separator or not key or (key in values and key != allowed_duplicate):
            raise ValueError(f"Invalid or duplicate env key at {path.name}:{number}")
        values[key] = raw.strip().strip("\"'")
    return lines, values


def _atomic_write(path: Path, contents: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare(
    api_path: Path, sample_path: Path, daily_path: Path, *, dry_run: bool = False
) -> dict[str, str]:
    if daily_path.exists():
        raise ValueError("Daily worker env already exists; refusing to replace it")
    if not api_path.is_file() or not sample_path.is_file():
        raise ValueError("ERP source env is missing")
    # The existing API env has two distinct CAPTCHA secrets. The daily worker
    # does not serve login requests, so it receives its own random secret.
    api_lines, api = _read(api_path, allowed_duplicate="AUTH_CAPTCHA_HMAC_SECRET")
    _, sample = _read(sample_path, allowed_duplicate="AUTH_CAPTCHA_HMAC_SECRET")
    for values in (api, sample):
        if urlsplit(values.get("DATABASE_URL", "")).hostname != RDS_HOST:
            raise ValueError("ERP database target is not the approved RDS")
        if urlsplit(values.get("REDIS_URL", "")).hostname != "127.0.0.1":
            raise ValueError("ERP Redis target is not the ECS loopback")
    if (
        sample.get("FEISHU_SAMPLE_BASE_TOKEN") != BASE_TOKEN
        or sample.get("FEISHU_DAILY_VALID_CREATOR_TABLE_ID") != TABLE_ID
        or not sample.get("FEISHU_APP_ID")
        or not sample.get("FEISHU_APP_SECRET")
    ):
        raise ValueError("Dedicated Feishu app or target identity does not match")
    required_api = ("APP_ENV", "CORS_ORIGINS", "AUTH_CAPTCHA_HMAC_SECRET", "DATABASE_URL", "REDIS_URL")
    if any(not api.get(key) for key in required_api):
        raise ValueError("Required ERP runtime setting is missing")
    if api["APP_ENV"] != "production":
        raise ValueError("ERP API is not configured for production")
    token = api.get("AFFILIATE_EXPORT_SERVICE_TOKEN") or secrets.token_urlsafe(48)
    existing_tenant = api.get("AFFILIATE_EXPORT_TENANT_ID")
    if existing_tenant and existing_tenant != TENANT_ID:
        raise ValueError("Affiliate export tenant does not match")
    daily = {key: api[key] for key in required_api if key != "AUTH_CAPTCHA_HMAC_SECRET"}
    daily.update(
        AUTH_CAPTCHA_HMAC_SECRET=secrets.token_urlsafe(48),
        FEISHU_NEW_APP_ID=sample["FEISHU_APP_ID"],
        FEISHU_NEW_APP_SECRET=sample["FEISHU_APP_SECRET"],
        FEISHU_DAILY_VALID_CREATOR_TABLE_ID=TABLE_ID,
        AFFILIATE_EXPORT_SERVICE_TOKEN=token,
        AFFILIATE_EXPORT_TENANT_ID=TENANT_ID,
        AFFILIATE_EXPORT_URL=EXPORT_URL,
    )
    for value in daily.values():
        if any(character.isspace() or character in "#\"'\x00" for character in value):
            raise ValueError("Unsafe env value")
    if dry_run:
        return {
            "target": str(daily_path),
            "tenant": TENANT_ID,
            "table": TABLE_ID,
            "status": "preflight_ok",
        }
    # Prepare the receiver first; a crash here leaves a recoverable API env only.
    if not api.get("AFFILIATE_EXPORT_SERVICE_TOKEN") or not existing_tenant:
        backup = api_path.with_name(
            f"{api_path.name}.before-daily-{datetime.now(UTC):%Y%m%d%H%M%S}"
        )
        shutil.copyfile(api_path, backup)
        os.chmod(backup, 0o600)
        additions = []
        if not api.get("AFFILIATE_EXPORT_SERVICE_TOKEN"):
            additions.append(f"AFFILIATE_EXPORT_SERVICE_TOKEN={token}")
        if not existing_tenant:
            additions.append(f"AFFILIATE_EXPORT_TENANT_ID={TENANT_ID}")
        _atomic_write(api_path, "\n".join([*api_lines, *additions]) + "\n")
    _atomic_write(
        daily_path,
        "\n".join(f"{key}={value}" for key, value in daily.items()) + "\n",
    )
    return {
        "target": str(daily_path),
        "tenant": TENANT_ID,
        "table": TABLE_ID,
        "status": "prepared_not_started",
    }


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("STOP_ROOT_REQUIRED")
    dry_run = sys.argv[1:] == ["--check"]
    if sys.argv[1:] and not dry_run:
        raise SystemExit("Usage: ecs_prepare_daily_valid_env.py [--check]")
    result = prepare(API_ENV, SAMPLE_ENV, DAILY_ENV, dry_run=dry_run)
    print(
        f"DAILY_ENV_{'PREFLIGHT_OK' if dry_run else 'PREPARED'} "
        f"TENANT={result['tenant']} TABLE={result['table']} "
        "NO_SERVICE_RESTART NO_FEISHU_WRITES"
    )


if __name__ == "__main__":
    main()
