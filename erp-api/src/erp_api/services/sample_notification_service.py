from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.feishu_sample_change import parse_feishu_assignee
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_bd_assignment import CREATOR_LEVELS
from erp_api.services.sample_notification_avatar import (
    SampleNotificationAvatarError,
)
from erp_api.services.sample_notification_card import build_sample_notification_card
from erp_api.services.sample_notification_delivery import (
    delivery_evidence,
    is_retryable_notification_error,
    safe_notification_error_code,
)
from erp_api.services.sample_notification_idempotency import (
    notification_delivery_key,
)
from erp_api.services.sample_notification_product_image import (
    SampleNotificationProductImageError,
)


@dataclass(frozen=True)
class SampleNotificationResult:
    event_id: UUID
    status: str
    retry_after_seconds: int | None = None
    message_id: str | None = None


class SampleNotificationService:
    def __init__(
        self,
        repository,
        client,
        record_client,
        *,
        record_url_template: str,
        record_url_templates_by_shop: Mapping[UUID, str] | None = None,
        test_recipient_open_id: str | None,
        live_recipients_enabled: bool,
        max_attempts: int,
        retry_base_seconds: int,
        processing_timeout: timedelta,
        group_chat_id: str | None = None,
        avatar_service=None,
        product_image_service=None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._client = client
        self._record_client = record_client
        self._record_url_template = record_url_template
        self._record_url_templates_by_shop = dict(
            record_url_templates_by_shop or {}
        )
        self._test_recipient_open_id = test_recipient_open_id
        self._live_recipients_enabled = live_recipients_enabled
        self._group_chat_id = group_chat_id
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._processing_timeout = processing_timeout
        self._avatar_service = avatar_service
        self._product_image_service = product_image_service
        self._clock = clock

    async def list_due(
        self,
        *,
        tenant_id: UUID | None = None,
        shop_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, int]]:
        return await self._repository.list_due(
            now=self._clock(),
            processing_timeout=self._processing_timeout,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )

    async def shop_id_for_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> UUID | None:
        return await self._repository.shop_id_for_event(tenant_id, event_id)

    async def deliver(
        self, tenant_id: UUID, event_id: UUID
    ) -> SampleNotificationResult:
        now = self._clock()
        task = await self._repository.claim(
            tenant_id,
            event_id,
            now=now,
            processing_timeout=self._processing_timeout,
        )
        if task is None:
            return SampleNotificationResult(event_id, "skipped")
        try:
            message_id, message_sent_at = delivery_evidence(task.payload)
            group_message_id, _ = delivery_evidence(
                task.payload,
                message_key="group_message_id",
                sent_at_key="group_message_sent_at",
            )
            group_delivery_required = bool(
                self._live_recipients_enabled and self._group_chat_id
            )
            delivery_pending = message_id is None or (
                group_delivery_required and group_message_id is None
            )
            if self._live_recipients_enabled and delivery_pending:
                fields = await self._record_client_for(task.shop_id).get_record(
                    task.feishu_record_id
                )
                assignee = parse_feishu_assignee(fields.get("分配BD"))
                expected_name = task.payload.get("assigned_bd_name")
                if (
                    assignee.name != expected_name
                    or (assignee.open_id and assignee.open_id != task.recipient_open_id)
                ):
                    return await self._record_failure(
                        task, "sample_assignment_projection_missing", now,
                        retryable=True,
                    )
            if (
                self._live_recipients_enabled
                and delivery_pending
                and (
                    task.creator_level not in CREATOR_LEVELS
                    or not isinstance(task.creator_gmv_minor, int)
                    or task.creator_gmv_minor < 0
                )
            ):
                return await self._record_failure(
                    task,
                    "creator_profile_incomplete",
                    now,
                    retryable=True,
                )
            if delivery_pending:
                avatar_img_key = await self._avatar_img_key(task)
                product_img_keys = await self._product_img_keys(task)
                card = build_sample_notification_card(
                    task,
                    self._record_url_template_for(task.shop_id),
                    is_test=not self._live_recipients_enabled,
                    avatar_img_key=avatar_img_key,
                    product_img_keys=product_img_keys,
                )
            if message_id is None:
                message_id = await self._client.send_card(
                    recipient_open_id=self._recipient_open_id(task),
                    card=card,
                    idempotency_key=notification_delivery_key(
                        task,
                        channel="direct",
                        target_id=self._recipient_open_id(task),
                    ),
                )
                message_sent_at = now
                persisted = await self._repository.record_message_sent(
                    tenant_id,
                    event_id,
                    message_id=message_id,
                    sent_at=message_sent_at,
                )
                if not persisted:
                    return SampleNotificationResult(event_id, "skipped")
            if group_delivery_required and group_message_id is None:
                group_message_id = await self._client.send_card_to_chat(
                    chat_id=self._group_chat_id,
                    card=card,
                    idempotency_key=notification_delivery_key(
                        task,
                        channel="group",
                        target_id=self._group_chat_id,
                    ),
                )
                persisted = await self._repository.record_group_message_sent(
                    tenant_id,
                    event_id,
                    message_id=group_message_id,
                    sent_at=now,
                )
                if not persisted:
                    return SampleNotificationResult(event_id, "skipped")
            if message_sent_at is None:
                raise ValueError("Sample notification delivery time is missing.")
            await self._record_client_for(task.shop_id).update_system_fields(
                task.feishu_record_id,
                {
                    "通知状态": "已通知",
                    "通知时间": int(message_sent_at.timestamp() * 1000),
                },
            )
        except FeishuSampleError as error:
            return await self._record_failure(task, error.error_code, now)
        except SampleNotificationProductImageError:
            return await self._record_failure(
                task,
                "product_image_unavailable",
                now,
                retryable=True,
            )
        except (TypeError, ValueError):
            return await self._record_failure(
                task, "invalid_notification_payload", now, retryable=False
            )
        await self._repository.succeed(tenant_id, event_id, sent_at=message_sent_at)
        return SampleNotificationResult(event_id, "sent", message_id=message_id)

    async def _avatar_img_key(self, task) -> str | None:
        if self._avatar_service is None or not task.creator_avatar_object_key:
            return None
        try:
            return await self._avatar_service.resolve_img_key(
                task.creator_avatar_object_key
            )
        except SampleNotificationAvatarError:
            return None

    async def _product_img_keys(self, task) -> tuple[str, ...]:
        if self._product_image_service is None:
            if self._live_recipients_enabled:
                raise SampleNotificationProductImageError(
                    "Product image service is unavailable."
                )
            return ()
        image_keys = []
        for image_url in task.product_image_urls:
            try:
                image_keys.append(
                    await self._product_image_service.resolve_img_key(image_url)
                )
            except (SampleNotificationProductImageError, ValueError):
                continue
        if self._live_recipients_enabled and not image_keys:
            raise SampleNotificationProductImageError(
                "Product images are unavailable."
            )
        return tuple(image_keys)

    async def _record_failure(
        self,
        task,
        code: str,
        now: datetime,
        *,
        retryable: bool | None = None,
    ) -> SampleNotificationResult:
        safe_code = safe_notification_error_code(code)
        can_retry = (
            is_retryable_notification_error(safe_code)
            if retryable is None
            else retryable
        ) and task.attempt_count < self._max_attempts
        retry_seconds = (
            min(
                self._retry_base_seconds * (2 ** (task.attempt_count - 1)),
                3600,
            )
            if can_retry
            else None
        )
        retry_at = now + timedelta(seconds=retry_seconds) if retry_seconds else None
        await self._repository.fail(
            task.tenant_id,
            task.id,
            code=safe_code,
            summary="Feishu notification request failed.",
            retry_at=retry_at,
        )
        return SampleNotificationResult(
            task.id,
            "retry_wait" if retry_at else "failed",
            retry_after_seconds=retry_seconds,
        )

    def _recipient_open_id(self, task) -> str:
        if self._live_recipients_enabled:
            return task.recipient_open_id
        if not self._test_recipient_open_id:
            raise ValueError("Sample notification test recipient is missing.")
        return self._test_recipient_open_id

    def _record_client_for(self, shop_id: UUID):
        if hasattr(self._record_client, "for_shop"):
            return self._record_client.for_shop(shop_id)
        return self._record_client

    def _record_url_template_for(self, shop_id: UUID) -> str:
        return self._record_url_templates_by_shop.get(
            shop_id, self._record_url_template
        )
