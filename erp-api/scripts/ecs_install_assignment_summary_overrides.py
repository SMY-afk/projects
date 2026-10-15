"""Install non-secret assignment-summary scope for a separate ECS container."""

import json
import os
import sys
import tempfile
from pathlib import Path
from uuid import UUID


SOURCE = Path("/etc/erp/erp-sample-worker.env")
TARGET = Path("/etc/erp/erp-assignment-summary-overrides.env")
KEYS = {
    "FEISHU_ASSIGNMENT_SUMMARY_SYNC_ENABLED",
    "FEISHU_ASSIGNMENT_SUMMARY_TABLE_ID",
    "FEISHU_ASSIGNMENT_SUMMARY_SHOP_IDS",
    "FEISHU_ASSIGNMENT_SUMMARY_BD_NAMES",
    "FEISHU_ASSIGNMENT_SUMMARY_BD_ALIASES",
    "FEISHU_ASSIGNMENT_SUMMARY_SYNC_INTERVAL_SECONDS",
}


def main() -> None:
    if os.geteuid() != 0 or not SOURCE.is_file():
        raise SystemExit("STOP_ASSIGNMENT_TARGET_IDENTITY")
    if TARGET.exists():
        existing = TARGET.read_text(encoding="utf-8").splitlines()
        if {line.partition("=")[0] for line in existing} != KEYS:
            raise SystemExit("STOP_ASSIGNMENT_EXISTING_KEYS")
    source = SOURCE.read_text(encoding="utf-8")
    if not all(
        f"{key}=" in source
        for key in (
            "DATABASE_URL",
            "REDIS_URL",
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_SAMPLE_BASE_TOKEN",
            "FEISHU_BD_ASSIGNMENT_RECORD_TABLE_ID",
        )
    ):
        raise SystemExit("STOP_ASSIGNMENT_BASE_ENV")
    config = json.load(sys.stdin)
    if not isinstance(config, dict) or set(config) != KEYS:
        raise SystemExit("STOP_ASSIGNMENT_KEYS")
    if any(
        not isinstance(value, str)
        or not value
        or any(character in value for character in ("'", "\n", "\r", "\x00"))
        for value in config.values()
    ):
        raise SystemExit("STOP_ASSIGNMENT_VALUES")
    if config["FEISHU_ASSIGNMENT_SUMMARY_SYNC_ENABLED"].lower() != "true":
        raise SystemExit("STOP_ASSIGNMENT_DISABLED")
    shops = config["FEISHU_ASSIGNMENT_SUMMARY_SHOP_IDS"].split(",")
    bds = config["FEISHU_ASSIGNMENT_SUMMARY_BD_NAMES"].split(",")
    try:
        shop_ids = {UUID(value.strip()) for value in shops}
        aliases = json.loads(config["FEISHU_ASSIGNMENT_SUMMARY_BD_ALIASES"])
    except (ValueError, TypeError, json.JSONDecodeError):
        raise SystemExit("STOP_ASSIGNMENT_SCOPE") from None
    if (
        len(shop_ids) != 5
        or len(bds) != 9
        or len(set(bds)) != 9
        or not isinstance(aliases, dict)
        or not set(aliases.values()) <= set(bds)
        or not config["FEISHU_ASSIGNMENT_SUMMARY_TABLE_ID"].startswith("tbl")
        or config["FEISHU_ASSIGNMENT_SUMMARY_SYNC_INTERVAL_SECONDS"] != "600"
    ):
        raise SystemExit("STOP_ASSIGNMENT_SCOPE")
    descriptor, temporary = tempfile.mkstemp(dir=TARGET.parent, prefix=".erp-assignment-summary.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for key in sorted(KEYS):
                handle.write(f"{key}={config[key]}\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, TARGET)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"ASSIGNMENT_OVERRIDES_INSTALLED MODE=600 SHOPS={len(shop_ids)} BDS={len(bds)}")


if __name__ == "__main__":
    main()
