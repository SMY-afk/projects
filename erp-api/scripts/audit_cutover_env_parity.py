"""Show only configuration key presence and equality across local and ECS."""

import io
import subprocess
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    local = dotenv_values(Path(".env"))
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "erp-ecs", "grep -E '^([A-Z0-9_]+)=' /etc/erp/erp-api.env"],
        capture_output=True, check=True, timeout=15,
    )
    ecs = dotenv_values(stream=io.StringIO(result.stdout.decode()))
    all_keys = sorted(set(local) | set(ecs))
    missing_ecs = [key for key in all_keys if local.get(key) and not ecs.get(key)]
    missing_local = [key for key in all_keys if ecs.get(key) and not local.get(key)]
    conflicting = [
        key for key in all_keys
        if local.get(key) and ecs.get(key) and local[key] != ecs[key]
    ]
    matching = [
        key for key in all_keys
        if local.get(key) and ecs.get(key) and local[key] == ecs[key]
    ]
    for label, keys in (
        ("LOCAL_ONLY_NONEMPTY", missing_ecs),
        ("ECS_ONLY_NONEMPTY", missing_local),
        ("BOTH_NONEMPTY_DIFFERENT", conflicting),
        ("BOTH_NONEMPTY_MATCH", matching),
    ):
        print(f"{label} COUNT={len(keys)} KEYS={','.join(keys)}")


if __name__ == "__main__":
    main()
