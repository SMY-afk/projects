from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class StoredObject:
    body: bytes
    content_type: str


class ObjectStorage(Protocol):
    provider: str
    bucket: str

    async def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def get(self, key: str) -> StoredObject: ...

    async def presign_get(self, key: str, *, expires_seconds: int) -> str: ...


class S3ObjectStorage:
    provider = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str | None,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        force_path_style: bool,
        key_prefix: str = "",
    ) -> None:
        if key_prefix and not re.fullmatch(
            r"(?:[A-Za-z0-9][A-Za-z0-9_-]*/)+", key_prefix
        ):
            raise ValueError(
                "Object storage key prefix must contain safe path segments and end in '/'."
            )
        self.bucket = bucket
        self._key_prefix = key_prefix
        endpoint_host = urlsplit(endpoint_url).hostname if endpoint_url else None
        is_oss_s3_endpoint = bool(
            endpoint_host
            and re.fullmatch(r"s3\.oss-[a-z0-9-]+\.aliyuncs\.com", endpoint_host)
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3" if is_oss_s3_endpoint else "s3v4",
                s3={"addressing_style": "path" if force_path_style else "virtual"},
            ),
        )

    async def put(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=self._key_prefix + key,
            Body=body,
            ContentType=content_type,
            Metadata=metadata,
            ACL="private",
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self.bucket, Key=self._key_prefix + key
        )

    async def get(self, key: str) -> StoredObject:
        def read_object() -> StoredObject:
            response = self._client.get_object(
                Bucket=self.bucket, Key=self._key_prefix + key
            )
            stream = response["Body"]
            try:
                body = stream.read()
            finally:
                stream.close()
            content_type = response.get("ContentType") or "application/octet-stream"
            return StoredObject(body=body, content_type=content_type)

        return await asyncio.to_thread(read_object)

    async def presign_get(self, key: str, *, expires_seconds: int) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key_prefix + key},
            ExpiresIn=expires_seconds,
        )
