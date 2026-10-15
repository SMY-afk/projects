"""Install an isolated ECS sample-worker env from SSH stdin without echoing values."""

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


SOURCE = Path("/etc/erp/erp-api.env")
TARGET = Path("/etc/erp/erp-sample-worker.env")
ALLOWED_PREFIXES = (
    "FEISHU_APP_",
    "FEISHU_SAMPLE_",
    "FEISHU_BD_",
    "FEISHU_AI_INVITATION_",
    "FEISHU_COOP_",
)
ALLOWED_EXACT = {
    "FEISHU_DAILY_VALID_CREATOR_TABLE_ID",
    "FEISHU_ASSIGNMENT_SUMMARY_BD_ALIASES",
}
REQUIRED = {
    "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_SAMPLE_BASE_TOKEN",
    "FEISHU_SAMPLE_TABLE_ID", "FEISHU_SAMPLE_SHOP_TABLE_IDS",
    "FEISHU_SAMPLE_NOTIFICATION_GROUP_CHAT_ID",
    "FEISHU_BD_ROSTER_TABLE_ID", "FEISHU_BD_ASSIGNMENT_RECORD_TABLE_ID",
}


def allowed(key: str) -> bool:
    return key in ALLOWED_EXACT or key.startswith(ALLOWED_PREFIXES)


def parse_lines(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    values = {}
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise SystemExit(f"STOP_BASE_ENV_FORMAT LINE={number} KEY={key[:50]}")
        values[key] = value.strip().strip("\"'")
    return lines, values


def main() -> None:
    if os.geteuid() != 0 or not SOURCE.is_file() or TARGET.exists():
        raise SystemExit("STOP_TARGET_IDENTITY")
    source_lines, base = parse_lines(SOURCE)
    critical_keys = {"DATABASE_URL", "REDIS_URL", "OBJECT_STORAGE_BUCKET", "OBJECT_STORAGE_KEY_PREFIX"}
    critical_keys.update(REQUIRED)
    if any(sum(line.startswith(f"{key}=") for line in source_lines) > 1 for key in critical_keys):
        raise SystemExit("STOP_DUPLICATE_CRITICAL_BASE_KEY")
    if (
        urlsplit(base.get("DATABASE_URL", "")).hostname
        != "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"
        or urlsplit(base.get("REDIS_URL", "")).hostname != "127.0.0.1"
        or base.get("OBJECT_STORAGE_BUCKET") != "wjvedio"
        or base.get("OBJECT_STORAGE_KEY_PREFIX") != "erp/"
    ):
        raise SystemExit("STOP_ECS_RUNTIME_TARGETS")
    incoming = json.load(sys.stdin)
    if (
        not isinstance(incoming, dict)
        or not REQUIRED.issubset(incoming)
        or any(not allowed(key) or key.startswith("FEISHU_NEW_") for key in incoming)
        or any(
            not isinstance(value, str) or not value
            or any(character in value for character in ("'", "\n", "\r", "\x00"))
            for value in incoming.values()
        )
    ):
        raise SystemExit("STOP_FEISHU_PAYLOAD")
    for flag in (
        "FEISHU_SAMPLE_NOTIFICATION_ENABLED",
        "FEISHU_SAMPLE_NOTIFICATION_LIVE_RECIPIENTS_ENABLED",
        "FEISHU_SAMPLE_REVERSE_POLL_ENABLED",
        "FEISHU_SAMPLE_AUTO_ASSIGNMENT_ENABLED",
    ):
        if incoming.get(flag, "").lower() != "true":
            raise SystemExit(f"STOP_DISABLED_FLAG={flag}")
    output = []
    replaced = set()
    for line in source_lines:
        key = line.partition("=")[0]
        if key in incoming:
            output.append(f"{key}='{incoming[key]}'")
            replaced.add(key)
        else:
            output.append(line)
    for key in sorted(incoming.keys() - replaced):
        output.append(f"{key}='{incoming[key]}'")
    descriptor, temporary = tempfile.mkstemp(dir=TARGET.parent, prefix=".erp-sample-worker.env.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, TARGET)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"SAMPLE_ENV_CREATED MODE=600 FEISHU_KEYS={len(incoming)} NO_SERVICE_RESTART")


if __name__ == "__main__":
    main()
