"""Read-only full OSS object comparison against preserved MinIO manifests."""

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


def manifest_items(path: Path) -> tuple[str, list[dict]]:
    with tarfile.open(path, "r:") as archive:
        source = archive.extractfile("manifest.json")
        require(source is not None, "STOP_MANIFEST_MISSING")
        with source:
            manifest = json.load(source)
    items = manifest.get("objects")
    require(isinstance(items, list), "STOP_MANIFEST_ITEMS")
    return manifest.get("bucket"), items


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path("/etc/erp/erp-api.env"))
    args = parser.parse_args()
    bucket_a, baseline = manifest_items(args.baseline)
    bucket_b, delta = manifest_items(args.delta)
    require(bucket_a == bucket_b == "erp-logistics", "STOP_SOURCE_BUCKET")
    expected = {}
    for item in baseline + delta:
        key = item["key"]
        require(key not in expected, "STOP_DUPLICATE_SOURCE_KEY")
        expected[key] = item
    settings = Settings(_env_file=args.env_file)
    require(settings.object_storage_bucket == "wjvedio", "STOP_TARGET_BUCKET")
    require(settings.object_storage_key_prefix == "erp/", "STOP_TARGET_PREFIX")
    require(settings.object_storage_access_key is not None, "STOP_TARGET_KEY")
    require(settings.object_storage_secret_key is not None, "STOP_TARGET_SECRET")
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
        key_prefix=settings.object_storage_key_prefix,
    )
    client = storage._client
    prefix = settings.object_storage_key_prefix
    actual = {}
    for page in client.get_paginator("list_objects").paginate(Bucket=storage.bucket, Prefix=prefix):
        for item in page.get("Contents", ()):
            require(item["Key"] not in actual, "STOP_DUPLICATE_TARGET_KEY")
            actual[item["Key"]] = item["Size"]
    require(set(actual) == {prefix + key for key in expected}, "STOP_TARGET_KEYS_DIFFER")
    for index, (key, item) in enumerate(sorted(expected.items()), 1):
        target_key = prefix + key
        require(actual[target_key] == item["size"], f"STOP_TARGET_SIZE_{index}")
        response = client.get_object(Bucket=storage.bucket, Key=target_key)
        body = response["Body"]
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := body.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        finally:
            body.close()
        require(size == item["size"] and digest.hexdigest() == item["sha256"], f"STOP_TARGET_BODY_{index}")
        require(response.get("ContentType") == item["content_type"], f"STOP_TARGET_TYPE_{index}")
        metadata = {k.lower(): v for k, v in response.get("Metadata", {}).items()}
        require(metadata == {k.lower(): v for k, v in item["metadata"].items()}, f"STOP_TARGET_METADATA_{index}")
        if index % 250 == 0 or index == len(expected):
            print(f"OSS_FULL_PROGRESS={index}/{len(expected)}", flush=True)
    print(f"OSS_FULL_VERIFY_OK OBJECTS={len(expected)} BYTES={sum(i['size'] for i in expected.values())} NO_OSS_WRITES")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        raise SystemExit(f"STOP_OSS_VERIFY TYPE={type(error).__name__}") from None
