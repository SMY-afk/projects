"""Send only active Feishu sample configuration to ECS over SSH stdin."""

import json
import subprocess

from dotenv import dotenv_values

from scripts.ecs_install_feishu_sample_env import ALLOWED_EXACT, ALLOWED_PREFIXES, REQUIRED


def main() -> None:
    values = dotenv_values(".env")
    selected = {
        key: value
        for key, value in values.items()
        if value and not key.startswith("FEISHU_NEW_")
        and (key in ALLOWED_EXACT or key.startswith(ALLOWED_PREFIXES))
    }
    if not REQUIRED.issubset(selected) or selected.get("FEISHU_APP_ID") != values.get("FEISHU_NEW_APP_ID"):
        raise SystemExit("STOP_LOCAL_FEISHU_IDENTITY")
    result = subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "erp-ecs", "/usr/bin/python3",
            "/opt/erp/imports/20261007-preflight/ecs_install_feishu_sample_env.py",
        ],
        input=json.dumps(selected, ensure_ascii=True),
        text=True,
        capture_output=True,
        timeout=25,
    )
    if result.returncode:
        raise SystemExit(f"STOP_ECS_SAMPLE_ENV_INSTALL EXIT={result.returncode} ERROR={result.stderr[-300:]}")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
