"""On ECS, atomically add only the source ERP encryption keys from stdin."""

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


TARGET = Path("/etc/erp/erp-api.env")
KEYS = (
    "TIKTOK_APP_KEY",
    "TIKTOK_SERVICE_ID",
    "TIKTOK_APP_SECRET",
    "TIKTOK_301_APP_KEY",
    "TIKTOK_301_SERVICE_ID",
    "TIKTOK_301_APP_SECRET",
    "TIKTOK_AUTHORIZATION_URL",
    "TIKTOK_TOKEN_URL",
    "TIKTOK_SHOP_IDENTITY_URL",
    "TIKTOK_CALLBACK_BASE_URL",
    "TIKTOK_TOKEN_ENCRYPTION_KEY",
    "TIKTOK_WEBHOOK_SIGNING_SECRET",
    "ORDER_PII_ENCRYPTION_KEY",
)


def main() -> None:
    if os.geteuid() != 0 or not TARGET.is_file():
        raise SystemExit("STOP_TARGET_IDENTITY")
    values = json.load(sys.stdin)
    if set(values) != set(KEYS) or any(
        not isinstance(values[key], str)
        or not values[key]
        or any(char in values[key] for char in ("\n", "\r", "'", "\\"))
        for key in KEYS
    ):
        raise SystemExit("STOP_SOURCE_KEY_VALUES")
    lines = TARGET.read_text(encoding="utf-8").splitlines()
    if not any(line.startswith("DATABASE_URL=") for line in lines):
        raise SystemExit("STOP_TARGET_ENV_IDENTITY")
    seen = set()
    updated = []
    changed = []
    for line in lines:
        key = line.split("=", 1)[0]
        if key not in KEYS:
            updated.append(line)
            continue
        if key in seen:
            raise SystemExit("STOP_DUPLICATE_KEY")
        seen.add(key)
        existing = line.split("=", 1)[1].strip().strip("\"'")
        if existing and existing != values[key]:
            raise SystemExit(f"STOP_EXISTING_KEY_MISMATCH={key}")
        updated.append(f"{key}='{values[key]}'")
        if not existing:
            changed.append(key)
    for key in KEYS:
        if key not in seen:
            updated.append(f"{key}='{values[key]}'")
            changed.append(key)
    if not changed:
        print("ERP_KEYS_ALREADY_MATCH")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = TARGET.with_name(f"erp-api.env.pre-keys-{stamp}")
    shutil.copy2(TARGET, backup)
    os.chmod(backup, 0o600)
    descriptor, temporary = tempfile.mkstemp(dir=TARGET.parent, prefix=".erp-api.env.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("\n".join(updated) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, TARGET)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"ERP_KEYS_UPDATED={','.join(changed)} BACKUP_CREATED=1")


if __name__ == "__main__":
    main()
