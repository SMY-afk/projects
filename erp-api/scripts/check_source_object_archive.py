"""Read-only comparison of live source objects with a preserved archive manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path

from erp_api.core.config import Settings
from erp_api.services.object_storage import S3ObjectStorage


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()

    with tarfile.open(args.archive, "r:") as archive:
        source = archive.extractfile("manifest.json")
        require(source is not None, "STOP_MANIFEST_MISSING")
        with source:
            manifest = json.load(source)
    items = manifest.get("objects")
    require(isinstance(items, list), "STOP_MANIFEST_ITEMS")

    settings = Settings()
    require(settings.object_storage_bucket == manifest.get("bucket"), "STOP_BUCKET")
    require(not settings.object_storage_key_prefix, "STOP_SOURCE_PREFIX")
    require(settings.object_storage_access_key is not None, "STOP_ACCESS_KEY")
    require(settings.object_storage_secret_key is not None, "STOP_SECRET_KEY")
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
    )
    client = storage._client

    expected = {item["key"]: item for item in items}
    require(len(expected) == len(items), "STOP_DUPLICATE_MANIFEST_KEY")
    listed: dict[str, int] = {}
    pages = client.get_paginator("list_objects_v2").paginate(Bucket=storage.bucket)
    for page in pages:
        for obj in page.get("Contents", ()):
            require(obj["Key"] not in listed, "STOP_DUPLICATE_SOURCE_KEY")
            listed[obj["Key"]] = obj["Size"]
    require(set(listed) == set(expected), "STOP_SOURCE_KEYS_CHANGED")
    print(f"SOURCE_KEYS_MATCH OBJECTS={len(listed)}", flush=True)

    total = 0
    for index, item in enumerate(items, 1):
        require(listed[item["key"]] == item["size"], f"STOP_SIZE INDEX={index}")
        response = client.get_object(Bucket=storage.bucket, Key=item["key"])
        body = response["Body"]
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := body.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        finally:
            body.close()
        require(size == item["size"], f"STOP_BODY_SIZE INDEX={index}")
        require(digest.hexdigest() == item["sha256"], f"STOP_SHA256 INDEX={index}")
        require(
            response.get("ContentType") == item["content_type"],
            f"STOP_CONTENT_TYPE INDEX={index}",
        )
        actual_metadata = {k.lower(): v for k, v in response.get("Metadata", {}).items()}
        expected_metadata = {k.lower(): v for k, v in item["metadata"].items()}
        require(actual_metadata == expected_metadata, f"STOP_METADATA INDEX={index}")
        total += size
        if index % 250 == 0 or index == len(items):
            print(f"SOURCE_CHECK_PROGRESS={index}/{len(items)}", flush=True)
    print(f"SOURCE_OBJECTS_MATCH OBJECTS={len(items)} BYTES={total}")


if __name__ == "__main__":
    main()
