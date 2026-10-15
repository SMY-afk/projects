"""Send one shop's durable RAW sample capture to the ECS HTTPS ingress."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.hubstudio_cdp import (
    normalize_loopback_cdp_url,
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from backend.app.services.hubstudio_cdp_ownership import assert_erp_hubstudio_cdp_url
from backend.app.services.sample_raw_batch_store import (
    SampleRawBatch,
    SampleRawBatchStore,
)
from backend.app.services.sample_raw_batch_validation import validate_stored_raw_pages
from backend.app.services.sample_raw_capture_retry import (
    capture_review_batch_with_retry,
)
from erp_api.services.remote_sample_capture import (
    RemoteSampleBatch,
    RemoteSamplePage,
    parse_complete_batch,
)


class CaptureIngressError(RuntimeError):
    def __init__(self, status_code: int, code: str):
        self.code = code
        super().__init__(f"ECS rejected RAW batch: HTTP {status_code} reason={code}")


async def reject_ingress_response(response, store, batch):
    code = f"http_{response.status_code}"
    remote_code = response.headers.get("x-erp-capture-error")
    if response.status_code == 409 and remote_code in {"busy", "stale_capture", "capture_conflict"}:
        code = remote_code
    if code == "stale_capture":
        await asyncio.to_thread(store.supersede_completed, batch)
    elif response.status_code == 503:
        code = "queue_unavailable"
    raise CaptureIngressError(response.status_code, code)


async def run(args: argparse.Namespace) -> None:
    store = getattr(args, "raw_store", None) or SampleRawBatchStore(args.spool_root, str(args.shop_id))
    batch = store.recover_completed()
    if args.verify_batch_sequence is not None:
        if batch is not None or args.capture:
            raise RuntimeError("Replay verification requires no pending capture")
        path = (
            args.spool_root
            / str(args.shop_id)
            / f"batch-{args.verify_batch_sequence:012d}"
        )
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "processed":
            raise RuntimeError("Replay verification requires a processed RAW batch")
        batch = SampleRawBatch(
            args.verify_batch_sequence,
            path,
            int(manifest["page_count"]),
            manifest.get("expected_total"),
            int(manifest["captured_total"]),
        )
    if batch is None and args.capture:
        url = normalize_loopback_cdp_url(args.cdp_url)
        if url is None or assert_erp_hubstudio_cdp_url(url) != url:
            raise RuntimeError("HubStudio CDP ownership is invalid")
        if not await probe_cdp_endpoint(url):
            raise RuntimeError("HubStudio CDP endpoint is unavailable")
        if await read_cdp_platform_shop_ids(url) != frozenset({args.platform_shop_id}):
            raise RuntimeError("HubStudio CDP shop identity does not match")
        capture = await asyncio.wait_for(
            capture_review_batch_with_retry(
                url, args.platform_shop_id, store,
                timeout_seconds=min(args.capture_timeout, 60),
            ),
            timeout=args.capture_timeout,
        )
        batch = capture.batch
    if batch is None:
        raise RuntimeError(
            "No completed RAW batch; rerun with --capture after preflight"
        )
    stored_pages = store.load_pages(batch)
    validate_stored_raw_pages(
        stored_pages, expected_total=batch.expected_total,
        captured_total=batch.captured_total, terminal_confirmed=True,
    )
    identity = f"{args.shop_id}:{batch.path.resolve()}"
    capture_id = uuid5(NAMESPACE_URL, identity)
    request = RemoteSampleBatch(
        sample_type=getattr(args, "sample_type", "free"),
        capture_id=capture_id,
        shop_id=args.shop_id,
        environment_id=args.environment_id,
        platform_shop_id=args.platform_shop_id,
        pages=[
            RemoteSamplePage(
                payload=dict(page.payload),
                request_id=page.request_id,
                observed_at=page.response_observed_at,
            )
            for page in stored_pages
        ],
    )
    parsed, _ = parse_complete_batch(request)
    if len(parsed) != batch.page_count:
        raise RuntimeError("RAW batch page count differs from manifest")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Capture token file is missing or too short")
    payload = request.model_dump_json().encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    if len(compressed) >= 1024 * 1024:
        raise RuntimeError("Compressed RAW batch exceeds ERP proxy limit")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        response = await client.post(
            args.api_url,
            content=compressed,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
                "x-erp-capture-token": token,
                "x-erp-capture-process": args.processing_mode,
            },
        )
    if response.status_code != 202:
        await reject_ingress_response(response, store, batch)
    receipt = response.json()
    if receipt.get("status") != "stored" or not receipt.get("batch_id"):
        raise RuntimeError("ECS did not return a durable RAW batch receipt")
    expected_processing = "queued" if args.processing_mode == "enqueue" else "deferred"
    if receipt.get("processing") != expected_processing:
        raise RuntimeError("ECS did not confirm requested business processing")
    if args.verify_batch_sequence is not None:
        if receipt.get("duplicate") is not True:
            raise RuntimeError("ECS did not identify the replay as a duplicate")
    else:
        await asyncio.to_thread(store.acknowledge, batch)
    print(
        f"RAW_BATCH_STORED shop={args.shop_id} capture={capture_id} "
        f"batch={receipt['batch_id']} pages={len(parsed)} "
        f"records={sum(len(page.applications) for page in parsed)} "
        f"duplicate={receipt.get('duplicate')} processing={args.processing_mode} "
        f"payload_sha256_prefix={digest}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--cdp-url")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--processing-mode", choices=("defer", "enqueue"), default="defer")
    parser.add_argument("--verify-batch-sequence", type=int)
    parser.add_argument("--capture-timeout", type=float, default=240)
    parser.add_argument(
        "--spool-root", type=Path, default=Path(".runtime/sample-raw-queue")
    )
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--api-url",
        default="https://example.invalid/configure-resource",
    )
    args = parser.parse_args()
    if not args.api_url.startswith("https://"):
        parser.error("HTTPS is required")
    if args.capture and not args.cdp_url:
        parser.error("--cdp-url is required with --capture")
    if args.verify_batch_sequence is not None and args.verify_batch_sequence <= 0:
        parser.error("--verify-batch-sequence must be positive")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
