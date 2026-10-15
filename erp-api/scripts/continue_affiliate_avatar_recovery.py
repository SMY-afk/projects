"""Continue historical avatar recovery only when existing shop capture guards allow it."""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from backend.app.services.windows_background_process import background_process_options

LABELS = {"50770999-40ce-5b84-bb01-13701932bdf1": "cross-border-4",
          "6fdc5cdc-90da-5524-82f7-9b11746c5e10": "local",
          "fe629cb8-fa7b-56a5-970c-2f6e9ebc5703": "cross-border-7",
          "5e1fed24-8268-5b5a-9ead-5efb862e7a51": "cross-border-12",
          "eb7678c2-67d6-5446-85f0-dc8fba9b75d6": "cross-border-3"}


def run(args, api, python=None, timeout=180):
    return subprocess.run([str(python or api / ".venv/Scripts/python.exe"), *args], cwd=api,
        env=dict(os.environ, PYTHONPATH="src;backend;."), capture_output=True, timeout=timeout, check=False,
        **background_process_options())


def recovery(root, api):
    audit = json.loads((root / "audit.json").read_text())
    endpoints = json.loads((root / "verified-endpoints.json").read_text())
    summary = {"scansPending": 0, "guardedScansCompleted": 0}
    for shop in audit["shops"]:
        label = LABELS[shop["shopId"]]
        state = json.loads((root / label / "state.json").read_text())
        windows = ((date.fromisoformat(shop["latest"]) - date.fromisoformat(shop["earliest"])).days + 30) // 30
        if state["window"] >= windows:
            continue
        summary["scansPending"] += 1
        command = ["scripts/collect_affiliate_avatar_cache.py", "--audit", str(root / "audit.json"),
                   "--output", str(root), "--shop-label", label, "--shop-id", shop["shopId"],
                   "--source-pages", "50", "--wait-seconds", "0", "--cdp-url", endpoints.get(label, "")]
        result = run(command, api)
        if result.returncode == 0:
            summary["guardedScansCompleted"] += 1
        else:
            matched = re.search(rb"AVATAR_ERROR type=\w+ code=([a-z_]+)", result.stdout)
            summary.setdefault("deferredOrFailed", {})[label] = matched.group(1).decode() if matched else "capture_failed"
    downloaded = run(["scripts/download_affiliate_avatars_sync.py", "--output", str(root)], api)
    if downloaded.returncode:
        raise RuntimeError("avatar_recovery_download_failed")
    prepared = run([str(root / "prepare_batch.py")], api, python=sys.executable)
    if prepared.returncode == 0:
        released = run([str(root / "send_batch.py")], api, python=sys.executable, timeout=300)
        if released.returncode:
            raise RuntimeError("avatar_recovery_publish_failed")
        batch = (root / "current-batch.txt").read_text().strip()
        summary["published"] = json.loads((root / "batches" / batch / "receipt.json").read_text())["updated"]
    elif b"No new image files are ready" not in prepared.stderr:
        raise RuntimeError("avatar_recovery_image_validation_failed")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--api", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(recovery(args.root, args.api)), flush=True)
