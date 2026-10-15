from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from erp_api.core.config import get_settings
from erp_api.services.object_storage import S3ObjectStorage

logger = logging.getLogger(__name__)

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
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class AffiliateVideoCoverStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredVideoCover:
    object_key: str


class AffiliateVideoCoverStorage:
    def __init__(
        self,
        storage,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 2_000_000,
        concurrency: int = 8,
    ) -> None:
        if timeout_seconds <= 0 or max_bytes <= 0 or concurrency <= 0:
            raise ValueError("Video cover storage limits are invalid.")
        self.object_storage = storage
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._operation_timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._concurrency = concurrency

    async def store(
        self,
        source_url: str,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        video_id: str,
    ) -> StoredVideoCover:
        _validate_source_url(source_url)
        _validate_video_id(video_id)
        if self._client is not None:
            return await self._store_with_client(
                self._client, source_url, tenant_id, shop_id, video_id
            )
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
        ) as client:
            return await self._store_with_client(
                client, source_url, tenant_id, shop_id, video_id
            )

    async def store_many(
        self,
        sources: dict[str, str],
        *,
        tenant_id: UUID,
        shop_id: UUID,
    ) -> dict[str, StoredVideoCover]:
        if not sources:
            return {}
        for video_id, source_url in sources.items():
            _validate_source_url(source_url)
            _validate_video_id(video_id)
        semaphore = asyncio.Semaphore(self._concurrency)

        async def store_one(client, video_id, source_url):
            async with semaphore:
                try:
                    return video_id, await self._store_with_client(
                        client, source_url, tenant_id, shop_id, video_id
                    )
                except AffiliateVideoCoverStorageError:
                    logger.warning(
                        "affiliate_video_cover_store_failed video_id=%s", video_id
                    )
                    return video_id, None

        if self._client is not None:
            pairs = await asyncio.gather(
                *(store_one(self._client, *item) for item in sources.items())
            )
        else:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                pairs = await asyncio.gather(
                    *(store_one(client, *item) for item in sources.items())
                )
        return {video_id: stored for video_id, stored in pairs if stored is not None}

    async def _store_with_client(
        self,
        client: httpx.AsyncClient,
        source_url: str,
        tenant_id: UUID,
        shop_id: UUID,
        video_id: str,
    ) -> StoredVideoCover:
        body, content_type = await self._download(client, source_url)
        object_key = video_cover_object_key(
            tenant_id, shop_id, video_id, _CONTENT_TYPES[content_type]
        )
        try:
            async with asyncio.timeout(self._operation_timeout_seconds):
                await self.object_storage.put(
                    object_key,
                    body,
                    content_type=content_type,
                    metadata={"source": "tiktok-affiliate"},
                )
        except Exception as error:
            raise AffiliateVideoCoverStorageError(
                "Video cover storage failed."
            ) from error
        return StoredVideoCover(object_key)

    async def _download(
        self, client: httpx.AsyncClient, source_url: str
    ) -> tuple[bytes, str]:
        try:
            async with client.stream("GET", source_url) as response:
                if response.status_code != 200:
                    raise AffiliateVideoCoverStorageError(
                        "Video cover download failed."
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type not in _CONTENT_TYPES:
                    raise AffiliateVideoCoverStorageError(
                        "Video cover type is unsupported."
                    )
                declared = response.headers.get("content-length")
                if declared and int(declared) > self._max_bytes:
                    raise AffiliateVideoCoverStorageError("Video cover is too large.")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise AffiliateVideoCoverStorageError(
                            "Video cover is too large."
                        )
                    chunks.append(chunk)
        except (httpx.HTTPError, ValueError) as error:
            raise AffiliateVideoCoverStorageError(
                "Video cover download failed."
            ) from error
        body = b"".join(chunks)
        if not body:
            raise AffiliateVideoCoverStorageError("Video cover is empty.")
        return body, content_type


class _CoverStorage(NamedTuple):
    storage: S3ObjectStorage
    url_ttl_seconds: int


async def presign_stored_video_covers(
    items: list[dict[str, object]],
) -> dict[str, str]:
    configured = _configured_storage()
    if configured is None:
        return {}
    keys = {
        video_id: object_key
        for item in items
        if (video_id := _text(item.get("videoId") or item.get("id")))
        and (object_key := _text(item.get("coverImageObjectKey")))
    }
    result: dict[str, str] = {}
    for video_id, object_key in keys.items():
        try:
            result[video_id] = await configured.storage.presign_get(
                object_key,
                expires_seconds=configured.url_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "affiliate_video_cover_presign_failed video_id=%s",
                video_id,
                exc_info=True,
            )
    return result


def video_cover_object_key(
    tenant_id, shop_id, video_id: str, extension: str | None = None
) -> str:
    suffix = f".{extension}" if extension else ""
    return f"affiliate/video-covers/{tenant_id}/{shop_id}/{video_id}{suffix}"


@lru_cache(maxsize=1)
def configured_video_cover_storage() -> S3ObjectStorage | None:
    configured = _configured_storage()
    return configured.storage if configured else None


@lru_cache(maxsize=1)
def configured_video_cover_writer() -> AffiliateVideoCoverStorage | None:
    storage = configured_video_cover_storage()
    return AffiliateVideoCoverStorage(storage) if storage else None


@lru_cache(maxsize=1)
def _configured_storage() -> _CoverStorage | None:
    settings = get_settings()
    if not (
        settings.object_storage_access_key
        and settings.object_storage_secret_key
        and settings.object_storage_bucket
    ):
        return None
    return _CoverStorage(
        storage=S3ObjectStorage(
            endpoint_url=settings.object_storage_endpoint_url,
            region=settings.object_storage_region,
            access_key=settings.object_storage_access_key.get_secret_value(),
            secret_key=settings.object_storage_secret_key.get_secret_value(),
            bucket=settings.object_storage_bucket,
            force_path_style=settings.object_storage_force_path_style,
            key_prefix=settings.object_storage_key_prefix,
        ),
        url_ttl_seconds=settings.object_storage_presigned_ttl_seconds,
    )


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = value.strip()
    return parsed or None


def _validate_source_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise AffiliateVideoCoverStorageError("Video cover URL is invalid.") from error
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
        raise AffiliateVideoCoverStorageError("Video cover URL is not allowed.")


def _validate_video_id(video_id: str) -> None:
    if not _VIDEO_ID.fullmatch(video_id):
        raise AffiliateVideoCoverStorageError("Video ID is invalid.")
