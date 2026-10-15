"""Download fresh official avatars locally, then publish only verified ERP avatar fields."""
import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.windows_background_process import background_process_options
from scripts.cache_affiliate_avatars_host import (
    OfficialRedirects,
    allowed,
    decode_image,
)

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "erp-ecs"]


def run(args):
    result = subprocess.run(
        args, capture_output=True, timeout=240, check=False,
        **background_process_options(),
    )
    if result.returncode:
        raise RuntimeError("avatar_cache_child_failed")
    return result.stdout


def fetch(record, root):
    try:
        if not allowed(record["url"]):
            raise ValueError("untrusted_avatar_origin")
        with urllib.request.build_opener(OfficialRedirects()).open(record["url"], timeout=8) as response:
            if response.status != 200 or not allowed(response.url):
                raise ValueError("invalid_avatar_response")
            body, content_type = response.read(2_000_001), response.headers.get_content_type()
        filename, digest = decode_image(body, content_type)
        target = root / "images" / filename
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
        else:
            # Exclusive creation prevents duplicate avatar writers overwriting the same file.
            try:
                with target.open("xb") as stream:
                    stream.write(body)
            except FileExistsError:
                pass
        return dict(record, file=filename, sha256=digest, bytes=len(body), contentType=content_type), None
    except Exception as error:  # noqa: BLE001 -- one unavailable photo must not discard verified ones
        return None, type(error).__name__


def main(args):
    root = args.root
    (root / "images").mkdir(parents=True, exist_ok=True)
    command = "docker cp /opt/erp/affiliate-avatar-cache/export_uncached_affiliate_avatars.py erp-ecs-api-1:/tmp/export_uncached_affiliate_avatars.py && docker exec erp-ecs-api-1 /opt/venv/bin/python /tmp/export_uncached_affiliate_avatars.py"
    records = json.loads(run(SSH + [command]))
    summary = {"freshUncached": len(records), "checkedAt": datetime.now(UTC).isoformat()}
    if records:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda row: fetch(row, root), records))
        verified = [record for record, error in results if record]
        summary.update(decodedImages=len(verified), failed=len(records) - len(verified))
        if verified:
            batch_id = hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()[:16]
            folder = root / "batches" / batch_id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "batch.json").write_text(json.dumps({"batchId": batch_id, "imagesValidated": True, "records": verified}))
            with tarfile.open(folder / "release.tar.gz", "w:gz") as archive:
                archive.add(folder / "batch.json", arcname="batch.json")
                for filename in ["publish_batch.py", "publish_asset_batch.py"]:
                    archive.add(root / filename, arcname=filename)
                for filename in {r["file"] for r in verified}:
                    archive.add(root / "images" / filename, arcname="images/" + filename)
            (root / "current-batch.txt").write_text(batch_id)
            run([sys.executable, str(root / "send_batch.py")])
            receipt = json.loads((folder / "receipt.json").read_text())
            summary.update(updated=receipt["updated"], publicHttpsVerified=True, batchId=batch_id)
    (root / "last-run.json").write_text(json.dumps(summary))
    if args.recovery_root:
        recovered = json.loads(run([sys.executable, "-m", "scripts.continue_affiliate_avatar_recovery",
            "--root", str(args.recovery_root), "--api", str(Path.cwd())]))
        summary["historicalRecovery"] = recovered
        (root / "last-run.json").write_text(json.dumps(summary))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recovery-root", type=Path)
    args = parser.parse_args()
    try:
        main(args)
    except Exception as error:  # noqa: BLE001 -- record sanitized task failure without URLs or credentials
        args.root.mkdir(parents=True, exist_ok=True)
        (args.root / "last-failure.json").write_text(json.dumps({"error": type(error).__name__,
            "at": datetime.now(UTC).isoformat()}))
        raise SystemExit(1) from None
