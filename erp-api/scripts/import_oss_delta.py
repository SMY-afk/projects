"""Import a verified MinIO delta to OSS without deleting or overwriting keys."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import tarfile
from pathlib import Path

from botocore.exceptions import ClientError

from erp_api.core.config import Settings
from erp_api.services.object_storage import S3ObjectStorage


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def load_archive(path: Path) -> list[dict]:
    with tarfile.open(path, "r:") as archive:
        source = archive.extractfile("manifest.json")
        require(source is not None, "STOP_DELTA_MANIFEST")
        with source:
            manifest = json.load(source)
        require(manifest.get("bucket") == "erp-logistics", "STOP_SOURCE_BUCKET")
        items = manifest.get("objects")
        require(isinstance(items, list), "STOP_DELTA_ITEMS")
        keys: set[str] = set()
        names: set[str] = set()
        for index, item in enumerate(items, 1):
            require(isinstance(item, dict), f"STOP_ITEM_{index}")
            key, name = item.get("key"), item.get("name")
            require(isinstance(key, str) and key and not key.startswith("/"), f"STOP_KEY_{index}")
            require(".." not in key.split("/") and "\\" not in key, f"STOP_KEY_{index}")
            require(isinstance(name, str) and re.fullmatch(r"objects/[0-9]{8}", name), f"STOP_NAME_{index}")
            require(key not in keys and name not in names, "STOP_DUPLICATE_DELTA")
            keys.add(key)
            names.add(name)
            require(type(item.get("size")) is int and item["size"] >= 0, f"STOP_SIZE_{index}")
            require(isinstance(item.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), f"STOP_HASH_{index}")
            require(isinstance(item.get("content_type"), str) and item["content_type"], f"STOP_TYPE_{index}")
            require(isinstance(item.get("metadata"), dict), f"STOP_METADATA_{index}")
            require(all(isinstance(k, str) and isinstance(v, str) for k, v in item["metadata"].items()), f"STOP_METADATA_{index}")
            member = archive.getmember(name)
            require(member.isfile() and member.size == item["size"], f"STOP_MEMBER_{index}")
            body = archive.extractfile(member)
            require(body is not None, f"STOP_MEMBER_{index}")
            with body:
                digest = hashlib.sha256()
                size = 0
                while chunk := body.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            require(size == item["size"] and digest.hexdigest() == item["sha256"], f"STOP_CONTENT_{index}")
    return items


def forbid_overwrite(request, **_kwargs) -> None:
    request.headers["x-oss-forbid-overwrite"] = "true"


def target_listing(client, bucket: str, prefix: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for page in client.get_paginator("list_objects").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", ()):
            require(item["Key"] not in result, "STOP_DUPLICATE_TARGET")
            result[item["Key"]] = item["Size"]
    return result


def verify_target(client, bucket: str, key: str, item: dict) -> None:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    require(size == item["size"] and digest.hexdigest() == item["sha256"], "STOP_TARGET_BODY")
    require(response.get("ContentType") == item["content_type"], "STOP_TARGET_TYPE")
    actual = {k.lower(): v for k, v in response.get("Metadata", {}).items()}
    expected = {k.lower(): v for k, v in item["metadata"].items()}
    require(actual == expected, "STOP_TARGET_METADATA")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path("/etc/erp/erp-api.env"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    items = load_archive(args.archive)
    print(f"DELTA_VERIFIED OBJECTS={len(items)} BYTES={sum(i['size'] for i in items)}", flush=True)
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
    client.meta.events.register("before-sign.s3.PutObject", forbid_overwrite)
    prefix = settings.object_storage_key_prefix
    uploaded = verified = 0
    try:
        existing = target_listing(client, storage.bucket, prefix)
        with tarfile.open(args.archive, "r:") as archive:
            for index, item in enumerate(items, 1):
                key = prefix + item["key"]
                if key in existing:
                    require(existing[key] == item["size"], f"STOP_EXISTING_SIZE_{index}")
                    verify_target(client, storage.bucket, key, item)
                    verified += 1
                    continue
                if not args.apply:
                    continue
                body = archive.extractfile(item["name"])
                require(body is not None, f"STOP_MEMBER_{index}")
                with body:
                    data = body.read()
                require(len(data) == item["size"], f"STOP_BODY_SIZE_{index}")
                md5 = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
                client.put_object(
                    Bucket=storage.bucket,
                    Key=key,
                    Body=data,
                    ContentLength=len(data),
                    ContentMD5=md5,
                    ContentType=item["content_type"],
                    Metadata=item["metadata"],
                    ACL="private",
                )
                verify_target(client, storage.bucket, key, item)
                uploaded += 1
                if index % 10 == 0 or index == len(items):
                    print(f"DELTA_PROGRESS={index}/{len(items)} UPLOADED={uploaded} VERIFIED={verified}", flush=True)
        final = target_listing(client, storage.bucket, prefix)
        if args.apply:
            require(all(final.get(prefix + item["key"]) == item["size"] for item in items), "STOP_FINAL_KEYS")
            print(f"DELTA_IMPORT_OK TARGET_OBJECTS={len(final)} UPLOADED={uploaded} VERIFIED={verified}")
        else:
            print(f"DELTA_CHECK_OK TARGET_OBJECTS={len(final)} MISSING={len(items) - verified} VERIFIED={verified} NO_OSS_WRITES")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "UNKNOWN"))
        safe = code if re.fullmatch(r"[A-Za-z0-9]+", code) else "UNKNOWN"
        raise SystemExit(f"STOP_OSS_API CODE={safe}") from None
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"STOP_IMPORT TYPE={type(exc).__name__}") from None


if __name__ == "__main__":
    main()
