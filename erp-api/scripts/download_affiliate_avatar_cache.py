"""Download already proven public avatar URLs without opening or occupying a shop browser."""
import argparse
import asyncio
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import httpx

platform._wmi = None

from scripts.affiliate_avatar_images import official_avatar_url, store_image


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


async def main(args):
    root = args.output
    ledgers = {}
    pending = []
    for path in root.glob("*/state.json"):
        label = path.parent.name
        state = json.loads(path.read_text())
        ledger = root / "downloads" / (label + ".json")
        images = json.loads(ledger.read_text()) if ledger.exists() else {}
        ledgers[label] = images
        for name, record in state["sources"].items():
            if name not in state["images"] and name not in images and official_avatar_url(record["url"]):
                pending.append(dict(record, sourceLabel=label))
    gate = asyncio.Semaphore(16)
    failures = []
    completed = 0
    attempted = 0
    async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                 headers={"Connection": "close", "Accept": "image/jpeg,image/png,image/webp,image/gif"},
                                 limits=httpx.Limits(max_connections=32)) as client:
        async def fetch(record):
            nonlocal completed, attempted
            async with asyncio.timeout(12):
                try:
                    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as image_client, image_client.stream("GET", record["url"]) as response:
                        if response.status_code != 200:
                            failures.append({"label": record["sourceLabel"], "name": record["name"], "error": "http_" + str(response.status_code)})
                            return
                        content_type = response.headers.get("content-type", "").split(";", 1)[0]
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 2_000_000:
                                raise ValueError("avatar_size_exceeded")
                            chunks.append(chunk)
                    image = store_image(root / "images", b"".join(chunks), content_type)
                    label = record["sourceLabel"]
                    ledgers[label][record["name"]] = dict(image, username=record["name"],
                        sourceIdentity=record["sourceIdentity"], observedAt=record["observedAt"],
                        storedAt=datetime.now(UTC).isoformat())
                    completed += 1
                    if completed % 100 == 0:
                        for key, value in ledgers.items():
                            save(root / "downloads" / (key + ".json"), value)
                        print(f"DIRECT_AVATARS_CACHED={completed}/{len(pending)}", flush=True)
                except Exception as error:
                    failures.append({"label": record["sourceLabel"], "name": record["name"], "error": type(error).__name__})
                finally:
                    attempted += 1
                    if attempted % 100 == 0:
                        from collections import Counter
                        save(root / "direct-download-progress.json", {"attempted": attempted, "cached": completed, "failed": len(failures), "errors": dict(Counter(item["error"] for item in failures))})
                        print(f"DIRECT_AVATAR_PROGRESS attempted={attempted} cached={completed} failed={len(failures)}", flush=True)
        async def bounded(record):
            async with gate:
                try:
                    await fetch(record)
                except TimeoutError:
                    failures.append({"label": record["sourceLabel"], "name": record["name"], "error": "total_timeout"})
        await asyncio.gather(*(bounded(record) for record in pending[:args.limit]))
    for key, value in ledgers.items():
        save(root / "downloads" / (key + ".json"), value)
    save(root / "direct-download-failures.json", failures)
    print(json.dumps({"directAvatarsDownloaded": completed, "failures": len(failures)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20_000)
    asyncio.run(main(parser.parse_args()))
