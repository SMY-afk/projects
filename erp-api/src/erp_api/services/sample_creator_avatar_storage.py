from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from erp_api.core.config import Settings
from erp_api.services.object_storage import ObjectStorage, S3ObjectStorage

_ALLOWED_HOST_SUFFIXES = (
    ".tiktokcdn-us.com",
    ".tiktokcdn.com",
    ".tiktokcdn-eu.com",
)
_CONTENT_TYPES = {
    "image/gif": "gif",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


class SampleCreatorAvatarError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredCreatorAvatar:
    object_key: str
    source_hash: str


class SampleCreatorAvatarStorage:
    def __init__(
        self,
        storage: ObjectStorage,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 2_000_000,
    ) -> None:
        if timeout_seconds <= 0 or max_bytes <= 0:
            raise ValueError("Creator avatar storage limits are invalid.")
        self.object_storage = storage
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_bytes = max_bytes

    async def store(
        self,
        source_url: str,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        creator_open_id: str,
    ) -> StoredCreatorAvatar:
        _validate_source_url(source_url)
        body, content_type = await self._download(source_url)
        digest = hashlib.sha256(body).hexdigest()
        creator_ref = hashlib.sha256(creator_open_id.encode("utf-8")).hexdigest()[:24]
        object_key = (
            f"sample/creator-avatars/{tenant_id}/{shop_id}/"
            f"{creator_ref}/{digest}.{_CONTENT_TYPES[content_type]}"
        )
        try:
            await self.object_storage.put(
                object_key,
                body,
                content_type=content_type,
                metadata={"sha256": digest},
            )
        except Exception as error:
            raise SampleCreatorAvatarError("Creator avatar storage failed.") from error
        return StoredCreatorAvatar(object_key=object_key, source_hash=digest)

    async def _download(self, source_url: str) -> tuple[bytes, str]:
        if self._client is not None:
            return await self._download_with_client(self._client, source_url)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
        ) as client:
            return await self._download_with_client(client, source_url)

    async def _download_with_client(
        self,
        client: httpx.AsyncClient,
        source_url: str,
    ) -> tuple[bytes, str]:
        try:
            async with client.stream("GET", source_url) as response:
                if response.status_code != 200:
                    raise SampleCreatorAvatarError("Creator avatar download failed.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type not in _CONTENT_TYPES:
                    raise SampleCreatorAvatarError(
                        "Creator avatar type is unsupported."
                    )
                declared = response.headers.get("content-length")
                if declared and int(declared) > self._max_bytes:
                    raise SampleCreatorAvatarError("Creator avatar is too large.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise SampleCreatorAvatarError("Creator avatar is too large.")
                    chunks.append(chunk)
        except (httpx.HTTPError, ValueError) as error:
            raise SampleCreatorAvatarError("Creator avatar download failed.") from error
        body = b"".join(chunks)
        if not body:
            raise SampleCreatorAvatarError("Creator avatar is empty.")
        return body, content_type


def extract_creator_avatar_source(value: object) -> str | None:
    root = value if isinstance(value, Mapping) else {}
    creator = root.get("creator") if isinstance(root.get("creator"), Mapping) else root
    for source in (creator.get("performance"), creator):
        if not isinstance(source, Mapping):
            continue
        for candidate in (source.get("avatar_url"), source.get("avatar")):
            if url := _avatar_url(candidate):
                return url
    return None


def build_sample_creator_avatar_storage(
    settings: Settings,
) -> SampleCreatorAvatarStorage | None:
    if not (
        settings.object_storage_access_key
        and settings.object_storage_secret_key
        and settings.object_storage_bucket
    ):
        return None
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
        key_prefix=settings.object_storage_key_prefix,
    )
    return SampleCreatorAvatarStorage(storage)


def _avatar_url(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        for key in ("url", "avatar_url", "uri", "url_list"):
            if result := _avatar_url(value.get(key)):
                return result
    if isinstance(value, list):
        return next((result for item in value if (result := _avatar_url(item))), None)
    return None


def _validate_source_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise SampleCreatorAvatarError("Creator avatar URL is invalid.") from error
    host = (parsed.hostname or "").casefold()
    allowed = any(
        host == suffix[1:] or host.endswith(suffix) for suffix in _ALLOWED_HOST_SUFFIXES
    )
    if (
        parsed.scheme.casefold() != "https"
        or not allowed
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or not parsed.path
        or parsed.fragment
    ):
        raise SampleCreatorAvatarError("Creator avatar URL is not allowed.")
