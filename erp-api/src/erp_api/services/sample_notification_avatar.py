from __future__ import annotations

from erp_api.services.object_storage import ObjectStorage

_CONTENT_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}


class SampleNotificationAvatarError(RuntimeError):
    pass


class SampleNotificationAvatarService:
    def __init__(
        self,
        storage: ObjectStorage,
        feishu_client,
        *,
        max_bytes: int = 2_000_000,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("Notification avatar size limit must be positive.")
        self._storage = storage
        self._feishu_client = feishu_client
        self._max_bytes = max_bytes

    async def resolve_img_key(self, object_key: str) -> str:
        if (
            not object_key.startswith("sample/creator-avatars/")
            or ".." in object_key
            or "\\" in object_key
            or len(object_key) > 512
        ):
            raise ValueError("Creator avatar object key is invalid.")
        try:
            stored = await self._storage.get(object_key)
        except Exception as error:
            raise SampleNotificationAvatarError(
                "Stored creator avatar could not be loaded."
            ) from error
        content_type = stored.content_type.split(";", 1)[0]
        if (
            not stored.body
            or len(stored.body) > self._max_bytes
            or content_type not in _CONTENT_TYPES
        ):
            raise ValueError("Stored creator avatar is invalid.")
        try:
            return await self._feishu_client.upload_message_image(
                image=stored.body,
                content_type=content_type,
            )
        except Exception as error:
            raise SampleNotificationAvatarError(
                "Creator avatar could not be uploaded."
            ) from error
