"""Verify and import the preserved ERP object archive into an empty OSS prefix.

The import never deletes objects. Existing objects are downloaded and verified
before they are skipped; new writes request OSS's no-overwrite protection.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import tarfile
import uuid
from getpass import getpass
from pathlib import Path

from botocore.exceptions import ClientError

from erp_api.core.config import Settings
from erp_api.services.object_storage import S3ObjectStorage

EXPECTED_BUCKET = "erp-logistics"
TARGET_BUCKET = "wjvedio"
TARGET_ENDPOINT = "https://s3.oss-cn-shenzhen.aliyuncs.com"
TARGET_PREFIX = "erp/"
EXPECTED_OBJECTS = 2782
EXPECTED_BYTES = 321488365
EXPECTED_ARCHIVE_SHA256 = (
    "26f70c66b21be8aa653b441d796bf6d1621d3a9732316d0df021f281621545ce"
)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read_member(archive: tarfile.TarFile, item: dict) -> bytes:
    member = archive.getmember(item["name"])
    require(member.isfile() and member.size == item["size"], "STOP_MEMBER_SIZE")
    source = archive.extractfile(member)
    require(source is not None, "STOP_MEMBER_MISSING")
    with source:
        body = source.read()
    require(len(body) == item["size"], "STOP_MEMBER_LENGTH")
    require(hashlib.sha256(body).hexdigest() == item["sha256"], "STOP_MEMBER_HASH")
    return body


def verify_archive(path: Path) -> list[dict]:
    require(path.is_file(), "STOP_ARCHIVE_MISSING")
    require(file_sha256(path) == EXPECTED_ARCHIVE_SHA256, "STOP_ARCHIVE_SHA256")
    with tarfile.open(path, "r:") as archive:
        manifest_source = archive.extractfile("manifest.json")
        require(manifest_source is not None, "STOP_MANIFEST_MISSING")
        with manifest_source:
            manifest = json.load(manifest_source)
        require(manifest.get("bucket") == EXPECTED_BUCKET, "STOP_SOURCE_BUCKET")
        items = manifest.get("objects")
        require(
            isinstance(items, list) and len(items) == EXPECTED_OBJECTS,
            "STOP_OBJECT_COUNT",
        )
        names: set[str] = set()
        keys: set[str] = set()
        total = 0
        for item in items:
            require(isinstance(item, dict), "STOP_MANIFEST_ITEM")
            name = item.get("name")
            key = item.get("key")
            size = item.get("size")
            sha256 = item.get("sha256")
            metadata = item.get("metadata")
            require(
                isinstance(name, str) and bool(re.fullmatch(r"objects/[0-9]{8}", name)),
                "STOP_MEMBER_NAME",
            )
            require(
                isinstance(key, str)
                and key
                and not key.startswith(("/", TARGET_PREFIX)),
                "STOP_OBJECT_KEY",
            )
            require(".." not in key.split("/") and "\\" not in key, "STOP_OBJECT_KEY")
            require(type(size) is int and size >= 0, "STOP_OBJECT_SIZE")
            require(
                isinstance(sha256, str) and bool(re.fullmatch(r"[0-9a-f]{64}", sha256)),
                "STOP_OBJECT_HASH",
            )
            require(
                isinstance(item.get("content_type"), str)
                and bool(item["content_type"]),
                "STOP_CONTENT_TYPE",
            )
            require(
                isinstance(metadata, dict)
                and all(
                    isinstance(k, str) and isinstance(v, str)
                    for k, v in metadata.items()
                ),
                "STOP_METADATA",
            )
            require(name not in names and key not in keys, "STOP_DUPLICATE_MANIFEST")
            names.add(name)
            keys.add(key)
            read_member(archive, item)
            total += size
        require(total == EXPECTED_BYTES, "STOP_TOTAL_BYTES")
    print(f"ARCHIVE_VERIFIED OBJECTS={len(items)} BYTES={total}")
    return items


def list_target(client, bucket: str) -> dict[str, int]:
    result: dict[str, int] = {}
    # OSS's S3-compatible V2 continuation request failed signature validation
    # after the first 1,000 objects; V1 marker pagination was verified on ECS.
    pages = client.get_paginator("list_objects").paginate(
        Bucket=bucket, Prefix=TARGET_PREFIX
    )
    for page in pages:
        for obj in page.get("Contents", ()):
            require(obj["Key"] not in result, "STOP_DUPLICATE_TARGET")
            result[obj["Key"]] = obj["Size"]
    return result


def verify_target_object(client, bucket: str, item: dict) -> None:
    response = client.get_object(Bucket=bucket, Key=TARGET_PREFIX + item["key"])
    stream = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    finally:
        stream.close()
    require(
        size == item["size"] and digest.hexdigest() == item["sha256"],
        "STOP_TARGET_CONTENT",
    )
    require(
        response.get("ContentType") == item["content_type"], "STOP_TARGET_CONTENT_TYPE"
    )
    expected_metadata = {k.lower(): v for k, v in item["metadata"].items()}
    actual_metadata = {k.lower(): v for k, v in response.get("Metadata", {}).items()}
    require(actual_metadata == expected_metadata, "STOP_TARGET_METADATA")


def forbid_overwrite(request, **_kwargs) -> None:
    request.headers["x-oss-forbid-overwrite"] = "true"


def apply_import(path: Path, items: list[dict], env_file: Path) -> None:
    settings = Settings(_env_file=env_file)
    require(settings.object_storage_bucket == TARGET_BUCKET, "STOP_TARGET_BUCKET")
    require(
        settings.object_storage_endpoint_url == TARGET_ENDPOINT, "STOP_TARGET_ENDPOINT"
    )
    require(settings.object_storage_key_prefix == TARGET_PREFIX, "STOP_TARGET_PREFIX")

    key_id = getpass("OSS AccessKey ID (hidden): ")
    secret = getpass("OSS AccessKey Secret (hidden): ")
    require(
        bool(re.fullmatch(r"[A-Za-z0-9._=]+", key_id)) and bool(secret),
        "STOP_INVALID_CREDENTIAL_INPUT",
    )
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=key_id,
        secret_key=secret,
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
        key_prefix=settings.object_storage_key_prefix,
    )
    client = storage._client
    client.meta.events.register("before-sign.s3.PutObject", forbid_overwrite)
    expected = {TARGET_PREFIX + item["key"]: item for item in items}
    index = 0
    try:
        existing = list_target(client, storage.bucket)
        require(set(existing).issubset(expected), "STOP_UNEXPECTED_TARGET_OBJECT")
        probe_key = TARGET_PREFIX + "_migration_probe_" + uuid.uuid4().hex
        try:
            client.head_object(Bucket=storage.bucket, Key=probe_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            require(
                code in {"404", "NoSuchKey", "NotFound"}, "STOP_TARGET_READ_PERMISSION"
            )
        else:
            raise SystemExit("STOP_PROBE_KEY_COLLISION")

        uploaded = verified_existing = 0
        with tarfile.open(path, "r:") as archive:
            for index, item in enumerate(items, 1):
                destination = TARGET_PREFIX + item["key"]
                body = read_member(archive, item)
                if destination in existing:
                    require(existing[destination] == item["size"], "STOP_EXISTING_SIZE")
                    verified_existing += 1
                else:
                    content_md5 = base64.b64encode(hashlib.md5(body).digest()).decode(
                        "ascii"
                    )
                    try:
                        client.put_object(
                            Bucket=storage.bucket,
                            Key=destination,
                            Body=body,
                            ContentLength=len(body),
                            ContentMD5=content_md5,
                            ContentType=item["content_type"],
                            Metadata=item["metadata"],
                            ACL="private",
                        )
                        uploaded += 1
                    except ClientError as exc:
                        code = str(exc.response.get("Error", {}).get("Code", ""))
                        if code != "FileAlreadyExists":
                            raise
                        verified_existing += 1
                verify_target_object(client, storage.bucket, item)
                if index % 250 == 0 or index == len(items):
                    print(
                        f"PROGRESS={index}/{len(items)} UPLOADED={uploaded} EXISTING_VERIFIED={verified_existing}",
                        flush=True,
                    )

        final = list_target(client, storage.bucket)
        require(set(final) == set(expected), "STOP_FINAL_TARGET_KEYS")
        require(sum(final.values()) == EXPECTED_BYTES, "STOP_FINAL_TARGET_BYTES")
        print(f"TARGET_OSS_IMPORT_OK OBJECTS={len(final)} BYTES={sum(final.values())}")
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "UNKNOWN"))
        safe_code = code if re.fullmatch(r"[A-Za-z0-9]+", code) else "UNKNOWN"
        raise SystemExit(f"STOP_OSS_API INDEX={index} CODE={safe_code}") from None
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - never expose credential-bearing errors
        raise SystemExit(
            f"STOP_IMPORT INDEX={index} TYPE={type(exc).__name__}"
        ) from None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path("/etc/erp/erp-api.env"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    items = verify_archive(args.archive)
    if args.apply:
        apply_import(args.archive, items, args.env_file)
    else:
        print("CHECK_ONLY_OK NO_OSS_WRITES")


if __name__ == "__main__":
    main()
