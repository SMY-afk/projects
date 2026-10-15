"""Preserve new MinIO objects relative to a verified baseline archive.

This script never writes to MinIO. Use --verify-baseline during final cutover
to prove that older keys still have the same body and metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path

from erp_api.core.config import get_settings
from erp_api.services.object_storage import S3ObjectStorage


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def read_baseline(path: Path) -> tuple[str, dict[str, dict]]:
    with tarfile.open(path, "r:") as archive:
        source = archive.extractfile("manifest.json")
        require(source is not None, "STOP_BASELINE_MANIFEST")
        with source:
            manifest = json.load(source)
    items = manifest.get("objects")
    require(isinstance(items, list), "STOP_BASELINE_ITEMS")
    old = {item["key"]: item for item in items}
    require(len(old) == len(items), "STOP_DUPLICATE_BASELINE_KEY")
    return manifest["bucket"], old


def digest_object(client, bucket: str, key: str, spool=None) -> tuple[int, str, dict]:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
            if spool is not None:
                spool.write(chunk)
    finally:
        body.close()
    return size, digest.hexdigest(), response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-baseline", action="store_true")
    args = parser.parse_args()
    require(not args.output.exists(), "STOP_OUTPUT_EXISTS")

    settings = get_settings()
    require(settings.object_storage_access_key is not None, "STOP_SOURCE_KEY")
    require(settings.object_storage_secret_key is not None, "STOP_SOURCE_SECRET")
    require(not settings.object_storage_key_prefix, "STOP_SOURCE_PREFIX")
    bucket, old = read_baseline(args.baseline_archive)
    require(bucket == settings.object_storage_bucket, "STOP_SOURCE_BUCKET")
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=bucket,
        force_path_style=settings.object_storage_force_path_style,
    )
    client = storage._client
    current: dict[str, int] = {}
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for item in page.get("Contents", ()):
            require(item["Key"] not in current, "STOP_DUPLICATE_SOURCE_KEY")
            current[item["Key"]] = item["Size"]
    require(set(old).issubset(current), "STOP_BASELINE_KEY_MISSING")
    require(
        all(current[key] == item["size"] for key, item in old.items()),
        "STOP_BASELINE_SIZE_CHANGED",
    )

    if args.verify_baseline:
        for index, (key, item) in enumerate(old.items(), 1):
            size, sha256, response = digest_object(client, bucket, key)
            require(size == item["size"] and sha256 == item["sha256"], f"STOP_BASELINE_BODY_{index}")
            require(response.get("ContentType") == item["content_type"], f"STOP_BASELINE_TYPE_{index}")
            metadata = {k.lower(): v for k, v in response.get("Metadata", {}).items()}
            require(metadata == {k.lower(): v for k, v in item["metadata"].items()}, f"STOP_BASELINE_METADATA_{index}")
            if index % 250 == 0 or index == len(old):
                print(f"BASELINE_VERIFIED={index}/{len(old)}", flush=True)

    new_keys = sorted(set(current) - set(old))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=args.output.name + ".", suffix=".partial", dir=args.output.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        items = []
        total = 0
        with tarfile.open(temporary, "w:") as archive:
            for index, key in enumerate(new_keys, 1):
                with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:
                    size, sha256, response = digest_object(client, bucket, key, spool)
                    require(size == current[key], f"STOP_CHANGED_DURING_EXPORT_{index}")
                    name = f"objects/{index:08d}"
                    member = tarfile.TarInfo(name)
                    member.size = size
                    spool.seek(0)
                    archive.addfile(member, spool)
                items.append(
                    {
                        "name": name,
                        "key": key,
                        "size": size,
                        "sha256": sha256,
                        "content_type": response.get("ContentType") or "application/octet-stream",
                        "metadata": response.get("Metadata", {}),
                    }
                )
                total += size
            payload = json.dumps(
                {"bucket": bucket, "baseline_objects": len(old), "objects": items},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            member = tarfile.TarInfo("manifest.json")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        require(not args.output.exists(), "STOP_OUTPUT_RACE")
        os.replace(temporary, args.output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(f"DELTA_ARCHIVE_OK OBJECTS={len(items)} BYTES={total} PATH={args.output}")


if __name__ == "__main__":
    main()
