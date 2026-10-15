"""Bounded independent HTTPS downloads of already verified official avatar URLs."""
import argparse
import http.client
import json
import platform
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

platform._wmi = None
from scripts.affiliate_avatar_images import official_avatar_url, store_image


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def fetch(record, root):
    try:
        with urllib.request.urlopen(record["url"], timeout=5) as response:
            if response.status != 200 or not official_avatar_url(response.url):
                return record, None, "invalid_response"
            body = response.read(2_000_001)
            content_type = response.headers.get_content_type()
        return record, store_image(root / "images", body, content_type), None
    except urllib.error.HTTPError as error:
        return record, None, f"http_{error.code}"
    except (OSError, ValueError, http.client.HTTPException) as error:
        return record, None, type(error).__name__


def main(args):
    root = args.output
    ledgers, pending = {}, []
    for path in root.glob("*/state.json"):
        label = path.parent.name
        state = json.loads(path.read_text())
        ledger = root / "downloads" / (label + ".json")
        images = json.loads(ledger.read_text()) if ledger.exists() else {}
        ledgers[label] = images
        for name, record in state["sources"].items():
            if name not in state["images"] and name not in images and official_avatar_url(record["url"]):
                pending.append(dict(record, sourceLabel=label))
    failures, completed, attempted = [], 0, 0
    with ThreadPoolExecutor(max_workers=24) as executor:
        tasks = [executor.submit(fetch, record, root) for record in pending[:args.limit]]
        for task in as_completed(tasks):
            record, image, error = task.result()
            if error:
                failures.append({"label": record["sourceLabel"], "name": record["name"], "error": error})
            else:
                ledgers[record["sourceLabel"]][record["name"]] = dict(image, username=record["name"],
                    sourceIdentity=record["sourceIdentity"], observedAt=record["observedAt"],
                    storedAt=datetime.now(UTC).isoformat())
                completed += 1
            attempted += 1
            if attempted % 200 == 0:
                for label, images in ledgers.items():
                    save(root / "downloads" / (label + ".json"), images)
                progress = {"attempted": attempted, "cached": completed, "failed": len(failures),
                            "errors": dict(Counter(f["error"] for f in failures))}
                save(root / "sync-download-progress.json", progress)
                print(json.dumps(progress), flush=True)
    for label, images in ledgers.items():
        save(root / "downloads" / (label + ".json"), images)
    save(root / "sync-download-failures.json", failures)
    print(json.dumps({"downloaded": completed, "failures": len(failures)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=50_000)
    main(parser.parse_args())
