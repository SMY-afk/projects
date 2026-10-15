from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx

from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import DEFAULT_FEISHU_RETRY_DELAYS


class FeishuNotificationClient:
    """Send idempotent bot messages using the sample app token cache."""

    def __init__(
        self,
        token_provider,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delays: tuple[float, ...] = DEFAULT_FEISHU_RETRY_DELAYS,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        kwargs = {
            "token_provider": token_provider.tenant_access_token,
            "client": client,
            "retry_delays": retry_delays,
            "business_type": "notification",
        }
        if sleeper is not None:
            kwargs["sleeper"] = sleeper
        self._feishu = FeishuClient(**kwargs)

    async def send_text(
        self,
        *,
        recipient_open_id: str,
        text: str,
        idempotency_key: str,
    ) -> str:
        return await self._send_text(
            receive_id=recipient_open_id,
            receive_id_type="open_id",
            text=text,
            idempotency_key=idempotency_key,
        )

    async def send_text_to_chat(
        self,
        *,
        chat_id: str,
        text: str,
        idempotency_key: str,
    ) -> str:
        return await self._send_text(
            receive_id=chat_id,
            receive_id_type="chat_id",
            text=text,
            idempotency_key=idempotency_key,
        )

    async def _send_text(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        text: str,
        idempotency_key: str,
    ) -> str:
        if not receive_id or len(receive_id) > 255:
            raise ValueError("Feishu notification recipient is invalid.")
        if receive_id_type not in {"open_id", "chat_id"}:
            raise ValueError("Feishu notification recipient type is invalid.")
        if not text or len(text) > 20_000:
            raise ValueError("Feishu notification text is invalid.")
        if (
            not idempotency_key
            or len(idempotency_key) > 50
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValueError("Feishu notification idempotency key is invalid.")
        token = await self._feishu.tenant_access_token()
        payload = await self._feishu.request_json(
            "POST",
            "/open-apis/im/v1/messages",
            retry_mode="idempotent",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "uuid": idempotency_key,
            },
        )
        data = payload.get("data")
        message_id = data.get("message_id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise FeishuSampleError(
                "Feishu notification response is missing message_id.",
                error_code="invalid_response",
            )
        return message_id

    async def send_card(
        self,
        *,
        recipient_open_id: str,
        card: dict[str, object],
        idempotency_key: str,
    ) -> str:
        return await self._send_card(
            receive_id=recipient_open_id,
            receive_id_type="open_id",
            card=card,
            idempotency_key=idempotency_key,
        )

    async def send_card_to_chat(
        self,
        *,
        chat_id: str,
        card: dict[str, object],
        idempotency_key: str,
    ) -> str:
        return await self._send_card(
            receive_id=chat_id,
            receive_id_type="chat_id",
            card=card,
            idempotency_key=idempotency_key,
        )

    async def _send_card(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        card: dict[str, object],
        idempotency_key: str,
    ) -> str:
        if not receive_id or len(receive_id) > 255:
            raise ValueError("Feishu notification recipient is invalid.")
        if receive_id_type not in {"open_id", "chat_id"}:
            raise ValueError("Feishu notification recipient type is invalid.")
        content = _card_content(card)
        if (
            not idempotency_key
            or len(idempotency_key) > 50
            or any(character.isspace() for character in idempotency_key)
        ):
            raise ValueError("Feishu notification idempotency key is invalid.")
        return await self._feishu.send_card(
            receive_id=receive_id,
            receive_id_type=receive_id_type,
            content=content,
            idempotency_key=idempotency_key,
        )

    async def update_card(
        self,
        *,
        message_id: str,
        card: dict[str, object],
    ) -> None:
        if not message_id or len(message_id) > 255 or "/" in message_id:
            raise ValueError("Feishu notification message ID is invalid.")
        content = _card_content(card)
        token = await self._feishu.tenant_access_token()
        await self._feishu.request_json(
            "PATCH",
            f"/open-apis/im/v1/messages/{message_id}",
            retry_mode="idempotent",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": content},
        )

    async def delete_message(self, *, message_id: str) -> None:
        if not message_id or len(message_id) > 255 or "/" in message_id:
            raise ValueError("Feishu notification message ID is invalid.")
        token = await self._feishu.tenant_access_token()
        await self._feishu.request_json(
            "DELETE",
            f"/open-apis/im/v1/messages/{message_id}",
            retry_mode="idempotent",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def upload_message_image(
        self,
        *,
        image: bytes,
        content_type: str,
    ) -> str:
        allowed_types = {"image/gif", "image/jpeg", "image/png", "image/webp"}
        if not image or len(image) > 10_000_000 or content_type not in allowed_types:
            raise ValueError("Feishu notification image is invalid.")
        token = await self._feishu.tenant_access_token()
        payload = await self._feishu.request_json(
            "POST",
            "/open-apis/im/v1/images",
            retry_mode="rate_limit",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("creator-avatar", image, content_type)},
        )
        data = payload.get("data")
        image_key = data.get("image_key") if isinstance(data, dict) else None
        if not isinstance(image_key, str) or not image_key:
            raise FeishuSampleError(
                "Feishu image response is missing image_key.",
                error_code="invalid_response",
            )
        return image_key


def _card_content(card: dict[str, object]) -> str:
    try:
        content = json.dumps(
            card,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Feishu notification card is invalid.") from error
    if not card or len(content.encode("utf-8")) > 30_000:
        raise ValueError("Feishu notification card is invalid.")
    return content
