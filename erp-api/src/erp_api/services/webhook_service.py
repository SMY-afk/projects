from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.tiktok_webhook_event import TikTokWebhookEvent
from erp_api.services.token_cipher import TokenCipher

MAX_WEBHOOK_BODY_BYTES = 1_048_576
MAX_CLOCK_SKEW_SECONDS = 300


class WebhookService:
    def __init__(
        self, database: Database, signing_secret: str, pii_cipher: TokenCipher
    ) -> None:
        self._database = database
        self._secret = signing_secret.encode()
        self._pii_cipher = pii_cipher

    def verify(self, body: bytes, signature: str, timestamp: str) -> None:
        if len(body) > MAX_WEBHOOK_BODY_BYTES:
            raise ValueError("Webhook body is too large.")
        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            raise ValueError("Webhook timestamp is invalid.") from None
        if (
            abs(int(datetime.now(UTC).timestamp()) - timestamp_value)
            > MAX_CLOCK_SKEW_SECONDS
        ):
            raise ValueError("Webhook timestamp is outside the accepted window.")
        expected = hmac.new(
            self._secret, timestamp.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        candidate = signature.removeprefix("sha256=")
        if not hmac.compare_digest(expected, candidate):
            raise ValueError("Webhook signature is invalid.")

    async def store(
        self, payload: dict[str, object], body: bytes
    ) -> tuple[UUID, bool, UUID, UUID]:
        shop_external_id = _required_text(payload, "shop_id", "shopId")
        event_type = _required_text(payload, "event_type", "type")
        object_id = _optional_text(payload, "order_id", "object_id")
        occurred_at = _timestamp(payload.get("create_time") or payload.get("timestamp"))
        payload_hash = hashlib.sha256(body).hexdigest()
        platform_event_id = (
            _optional_text(payload, "event_id", "id")
            or hashlib.sha256(
                f"{event_type}|{object_id or ''}|{occurred_at.isoformat() if occurred_at else ''}|{payload_hash}".encode()
            ).hexdigest()
        )

        tenant_shop = await self._resolve_shop(shop_external_id)
        if tenant_shop is None:
            raise LookupError("Webhook shop is unknown.")
        tenant_id, shop_id = tenant_shop
        async for session in self._database.session(tenant_id):
            event = TikTokWebhookEvent(
                tenant_id=tenant_id,
                shop_id=shop_id,
                platform_event_id=platform_event_id,
                event_type=event_type,
                object_id=object_id,
                payload_ciphertext=self._pii_cipher.encrypt(body.decode("utf-8")),
                payload_hash=payload_hash,
                occurred_at=occurred_at,
            )
            session.add(event)
            try:
                await session.commit()
                return event.id, True, tenant_id, shop_id
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(TikTokWebhookEvent.id).where(
                        TikTokWebhookEvent.platform_event_id == platform_event_id
                    )
                )
                if existing:
                    return existing, False, tenant_id, shop_id
                raise
        raise RuntimeError("Tenant database session was not created.")

    async def _resolve_shop(self, external_id: str) -> tuple[UUID, UUID] | None:
        async with self._database.system_session_factory() as session:
            row = (
                await session.execute(
                    select(Shop.tenant_id, Shop.id).where(
                        Shop.platform == "tiktok", Shop.platform_shop_id == external_id
                    )
                )
            ).one_or_none()
            return (row[0], row[1]) if row else None

    async def get_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> TikTokWebhookEvent | None:
        async for session in self._database.session(tenant_id):
            return await session.get(TikTokWebhookEvent, event_id)
        return None

    async def finish_event(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        status: str,
        error_summary: str | None = None,
    ) -> None:
        async for session in self._database.session(tenant_id):
            await session.execute(
                update(TikTokWebhookEvent)
                .where(TikTokWebhookEvent.id == event_id)
                .values(
                    status=status,
                    error_summary=error_summary,
                    processed_at=datetime.now(UTC),
                    attempt_count=TikTokWebhookEvent.attempt_count + 1,
                )
            )
            await session.commit()
            return


def _required_text(data: dict[str, object], *keys: str) -> str:
    value = _optional_text(data, *keys)
    if not value:
        raise ValueError(f"Webhook field {keys[0]} is required.")
    return value


def _optional_text(data: dict[str, object], *keys: str) -> str | None:
    return next(
        (value for key in keys if isinstance((value := data.get(key)), str) and value),
        None,
    )


def _timestamp(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC) if value else None
    except (TypeError, ValueError):
        return None
