from __future__ import annotations

from urllib.parse import urlsplit

import httpx

_ALLOWED_HOST_SUFFIXES = (
    ".ttcdn-us.com",
    ".tiktokcdn-us.com",
    ".tiktokcdn.com",
    ".tiktokcdn-eu.com",
)
_CONTENT_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}


class SampleNotificationProductImageError(RuntimeError):
    pass


class SampleNotificationProductImageService:
    def __init__(
        self,
        feishu_client,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
        max_bytes: int = 5_000_000,
    ) -> None:
        if timeout_seconds <= 0 or max_bytes <= 0:
            raise ValueError("Product image limits are invalid.")
        self._feishu_client = feishu_client
        self._client = client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_bytes = max_bytes

    async def resolve_img_key(self, source_url: str) -> str:
        _validate_source_url(source_url)
        body, content_type = await self._download(source_url)
        try:
            return await self._feishu_client.upload_message_image(
                image=body,
                content_type=content_type,
            )
        except Exception as error:
            raise SampleNotificationProductImageError(
                "Product image could not be uploaded."
            ) from error

    async def is_available(self, source_url: str) -> bool:
        try:
            _validate_source_url(source_url)
            body, content_type = await self._download(source_url)
        except SampleNotificationProductImageError:
            return False
        return _has_image_signature(body, content_type)

    async def _download(self, source_url: str) -> tuple[bytes, str]:
        if self._client is not None:
            return await self._download_with_client(self._client, source_url)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
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
                    raise SampleNotificationProductImageError(
                        "Product image download failed."
                    )
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type not in _CONTENT_TYPES:
                    raise SampleNotificationProductImageError(
                        "Product image type is unsupported."
                    )
                declared = response.headers.get("content-length")
                if declared and int(declared) > self._max_bytes:
                    raise SampleNotificationProductImageError(
                        "Product image is too large."
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise SampleNotificationProductImageError(
                            "Product image is too large."
                        )
                    chunks.append(chunk)
        except (httpx.HTTPError, ValueError) as error:
            raise SampleNotificationProductImageError(
                "Product image download failed."
            ) from error
        body = b"".join(chunks)
        if not body:
            raise SampleNotificationProductImageError("Product image is empty.")
        return body, content_type


def _validate_source_url(value: str) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise SampleNotificationProductImageError(
            "Product image URL is invalid."
        ) from error
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
        raise SampleNotificationProductImageError("Product image URL is not allowed.")


def _has_image_signature(body: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return body.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return False
