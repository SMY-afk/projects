"""Send only assignment-summary scope to ECS over SSH stdin."""

import json
import subprocess

from dotenv import dotenv_values

from scripts.ecs_install_assignment_summary_overrides import KEYS


def main() -> None:
    local = dotenv_values(".env")
    config = {key: local.get(key) for key in KEYS}
    if any(not value for value in config.values()):
        raise SystemExit("STOP_LOCAL_ASSIGNMENT_SCOPE")
    result = subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "erp-ecs", "/usr/bin/python3",
            "/opt/erp/imports/20261007-preflight/ecs_install_assignment_summary_overrides.py",
        ],
        input=json.dumps(config, ensure_ascii=True),
        text=True,
        capture_output=True,
        timeout=25,
    )
    if result.returncode:
        raise SystemExit(
            f"STOP_ASSIGNMENT_OVERRIDE_INSTALL EXIT={result.returncode} "
            f"ERROR={result.stderr[-200:]}"
        )
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
