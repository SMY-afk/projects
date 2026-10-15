from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.sample_notification_due import is_notification_due
from erp_api.services.sample_notification_products import (
    list_notification_product_image_urls,
)
from erp_api.services.sample_type_policy import is_assignable_sample


@dataclass(frozen=True)
class ClaimedSampleNotification:
    id: UUID
    tenant_id: UUID
    shop_id: UUID
    recipient_open_id: str
    attempt_count: int
    payload: dict[str, object]
    shop_name: str
    creator_name: str
    creator_username: str | None
    creator_level: str | None
    follower_count: int | None
    creator_gmv_minor: int | None
    creator_gmv_currency: str | None
    creator_units_sold: int | None
    creator_ec_video_view: int | None
    creator_content_count: int | None
    creator_fulfillment_percentage: Decimal | None
    creator_pps: Decimal | None
    creator_rating: Decimal | None
    creator_avatar_object_key: str | None
    creator_profile_snapshot: dict[str, object] | None
    creator_profile_observed_at: datetime | None
    product_name: str
    product_image_urls: tuple[str, ...]
    platform_status: str
    approve_expiration_at: datetime | None
    source_observed_at: datetime
    feishu_record_id: str
    sample_type: str = "free"


class SampleNotificationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def shop_id_for_event(
        self, tenant_id: UUID, event_id: UUID
    ) -> UUID | None:
        async with self._database.system_session_factory() as session:
            return await session.scalar(
                select(SampleNotificationOutbox.shop_id).where(
                    SampleNotificationOutbox.tenant_id == tenant_id,
                    SampleNotificationOutbox.id == event_id,
                    SampleNotificationOutbox.status.in_(
                        ("pending", "retry_wait", "processing")
                    ),
                )
            )

    async def list_due(
        self,
        *,
        now: datetime,
        processing_timeout: timedelta,
        limit: int = 200,
        tenant_id: UUID | None = None,
        shop_id: UUID | None = None,
    ) -> list[tuple[UUID, UUID, int]]:
        if now.tzinfo is None or not 1 <= limit <= 500:
            raise ValueError("Sample notification due query is invalid.")
        if (tenant_id is None) != (shop_id is None):
            raise ValueError("Notification tenant and shop filters must be paired.")
        statement = select(
            SampleNotificationOutbox.tenant_id,
            SampleNotificationOutbox.id,
            SampleNotificationOutbox.attempt_count,
        ).where(
            or_(
                SampleNotificationOutbox.status == "pending",
                (SampleNotificationOutbox.status == "retry_wait")
                & (SampleNotificationOutbox.next_attempt_at <= now),
                (SampleNotificationOutbox.status == "processing")
                & (SampleNotificationOutbox.updated_at <= now - processing_timeout),
            )
        )
        if tenant_id is not None and shop_id is not None:
            statement = statement.where(
                SampleNotificationOutbox.tenant_id == tenant_id,
                SampleNotificationOutbox.shop_id == shop_id,
            )
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    statement.order_by(SampleNotificationOutbox.created_at).limit(limit)
                )
            ).all()
        return [
            (tenant_id, event_id, attempts) for tenant_id, event_id, attempts in rows
        ]

    async def claim(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        now: datetime,
        processing_timeout: timedelta,
    ) -> ClaimedSampleNotification | None:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                SampleNotificationOutbox, event_id, with_for_update=True
            )
            if event is None or not is_notification_due(event, now, processing_timeout):
                return None
            workflow = await session.scalar(
                select(SampleApplicationWorkflow)
                .where(
                    SampleApplicationWorkflow.tenant_id == tenant_id,
                    SampleApplicationWorkflow.shop_id == event.shop_id,
                    SampleApplicationWorkflow.sample_application_id
                    == event.sample_application_id,
                )
                .with_for_update()
            )
            if (
                workflow is None
                or workflow.assignment_version != event.assignment_version
            ):
                event.status = "cancelled"
                event.next_attempt_at = None
                await session.commit()
                return None
            if not isinstance(event.payload, dict):
                event.status = "failed"
                event.last_error_code = "invalid_notification_payload"
                event.last_error_summary = "Sample notification payload is invalid."
                await session.commit()
                return None
            if workflow.assigned_bd_name != event.payload.get("assigned_bd_name"):
                event.status = "failed"
                event.next_attempt_at = None
                event.last_error_code = "assignment_owner_mismatch"
                event.last_error_summary = (
                    "Local assignment owner differs from notification owner."
                )
                await session.commit()
                return None
            context = (
                await session.execute(
                    select(
                        Shop.shop_name,
                        SampleApplication.creator_nickname,
                        SampleApplication.creator_username,
                        SampleApplication.creator_open_id,
                        SampleApplication.creator_level,
                        SampleApplication.follower_count,
                        SampleApplication.creator_gmv_minor,
                        SampleApplication.creator_gmv_currency,
                        SampleApplication.creator_units_sold,
                        SampleApplication.creator_ec_video_view,
                        SampleApplication.creator_content_count,
                        SampleApplication.creator_fulfillment_percentage,
                        SampleApplication.creator_pps,
                        SampleApplication.creator_rating,
                        SampleApplication.creator_avatar_object_key,
                        SampleApplication.creator_profile_snapshot,
                        SampleApplication.creator_profile_observed_at,
                        SampleApplication.product_title,
                        SampleApplication.sku_name,
                        SampleApplication.product_id,
                        SampleApplication.sku_image_url,
                        SampleApplication.product_image_urls,
                        SampleApplication.platform_status,
                        SampleApplication.approve_expiration_at,
                        SampleApplication.source_observed_at,
                        SampleApplication.raw_payload,
                        SampleApplication.is_current_projection,
                        SampleApplication.is_approvable,
                        SampleApplication.sample_type,
                    )
                    .join(
                        Shop,
                        and_(
                            Shop.id == SampleApplication.shop_id,
                            Shop.tenant_id == SampleApplication.tenant_id,
                        ),
                    )
                    .where(
                        SampleApplication.id == event.sample_application_id,
                        SampleApplication.tenant_id == tenant_id,
                        SampleApplication.shop_id == event.shop_id,
                    )
                )
            ).one_or_none()
            if context is None or not workflow.feishu_record_id:
                event.status = "failed"
                event.last_error_code = "notification_context_missing"
                event.last_error_summary = "Sample notification context is missing."
                await session.commit()
                return None
            (
                shop_name,
                creator_nickname,
                creator_username,
                creator_open_id,
                creator_level,
                follower_count,
                creator_gmv_minor,
                creator_gmv_currency,
                creator_units_sold,
                creator_ec_video_view,
                creator_content_count,
                creator_fulfillment_percentage,
                creator_pps,
                creator_rating,
                creator_avatar_object_key,
                creator_profile_snapshot,
                creator_profile_observed_at,
                product_title,
                sku_name,
                product_id,
                product_image_url,
                stored_product_image_urls,
                platform_status,
                approve_expiration_at,
                source_observed_at,
                raw_payload,
                is_current_projection,
                is_approvable,
                *type_context,
            ) = context
            sample_type = type_context[0] if type_context else "free"
            if is_current_projection is not True:
                event.status = "cancelled"
                event.next_attempt_at = None
                event.last_error_code = "superseded_application_projection"
                event.last_error_summary = (
                    "A current grouped projection replaced this application."
                )
                await session.commit()
                return None
            if not is_assignable_sample(SimpleNamespace(
                sample_type=sample_type, platform_status=platform_status,
                is_current_projection=is_current_projection, is_approvable=is_approvable,
                approve_expiration_at=approve_expiration_at, raw_payload=raw_payload,
                source_observed_at=source_observed_at,
                creator_username=creator_username,
            ), now=now):
                event.status = "cancelled"
                event.next_attempt_at = None
                event.last_error_code = "non_approvable_application"
                event.last_error_summary = (
                    "Notification cancelled because the current application "
                    "is not approvable."
                )
                await session.commit()
                return None
            if (
                sample_type == "free" and (
                not isinstance(raw_payload, dict)
                or not isinstance(
                    raw_payload.get("is_proactive_invitation"), bool
                )
                )
            ):
                event.status = "cancelled"
                event.next_attempt_at = None
                event.last_error_code = "unverified_application_source"
                event.last_error_summary = (
                    "Notification cancelled because the TikTok application source "
                    "was not verified."
                )
                await session.commit()
                return None
            if creator_open_id:
                creator_match = SampleApplication.creator_open_id == creator_open_id
            elif creator_username:
                creator_match = (
                    func.lower(
                        func.ltrim(func.trim(SampleApplication.creator_username), "@")
                    )
                    == creator_username.strip().lstrip("@").casefold()
                )
            else:
                creator_match = SampleApplication.id == event.sample_application_id
            latest_creator_event_id = await session.scalar(
                select(SampleNotificationOutbox.id)
                .join(
                    SampleApplication,
                    SampleApplication.id
                    == SampleNotificationOutbox.sample_application_id,
                )
                .where(
                    SampleNotificationOutbox.tenant_id == tenant_id,
                    SampleNotificationOutbox.shop_id == event.shop_id,
                    SampleNotificationOutbox.status != "cancelled",
                    SampleNotificationOutbox.payload["source_event_id"].astext.like(
                        "bd-auto:%"
                    ),
                    SampleApplication.is_current_projection.is_(True),
                    SampleApplication.sample_type == sample_type,
                    SampleApplication.id == event.sample_application_id
                    if sample_type == "refundable" else creator_match,
                )
                .order_by(
                    SampleNotificationOutbox.created_at.desc(),
                    SampleNotificationOutbox.id.desc(),
                )
                .limit(1)
            )
            if latest_creator_event_id != event.id:
                event.status = "cancelled"
                event.next_attempt_at = None
                event.last_error_code = "duplicate_creator_shop_notification"
                event.last_error_summary = (
                    "A newer notification for this creator and shop was retained."
                )
                await session.commit()
                return None
            product_image_urls = await list_notification_product_image_urls(
                session,
                tenant_id=tenant_id,
                shop_id=event.shop_id,
                application_id=event.sample_application_id,
                platform_status=platform_status,
                creator_open_id=creator_open_id,
                creator_username=creator_username,
                fallback_image_url=product_image_url,
                stored_image_urls=tuple(stored_product_image_urls or ()),
                sample_type=sample_type,
            )
            event.status = "processing"
            event.attempt_count += 1
            event.next_attempt_at = None
            await session.commit()
            return ClaimedSampleNotification(
                event.id,
                event.tenant_id,
                event.shop_id,
                event.recipient_open_id,
                event.attempt_count,
                dict(event.payload),
                shop_name,
                creator_nickname or creator_username or creator_open_id or "未知达人",
                creator_username,
                creator_level,
                follower_count,
                creator_gmv_minor,
                creator_gmv_currency,
                creator_units_sold,
                creator_ec_video_view,
                creator_content_count,
                creator_fulfillment_percentage,
                creator_pps,
                creator_rating,
                creator_avatar_object_key,
                creator_profile_snapshot,
                creator_profile_observed_at,
                product_title or sku_name or product_id or "未知商品",
                product_image_urls,
                platform_status,
                approve_expiration_at,
                source_observed_at,
                workflow.feishu_record_id,
                sample_type,
            )
        return None

    async def record_message_sent(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime,
    ) -> bool:
        return await self._record_delivery_sent(
            tenant_id,
            event_id,
            message_id=message_id,
            sent_at=sent_at,
            message_key="message_id",
            sent_at_key="message_sent_at",
        )

    async def record_group_message_sent(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime,
    ) -> bool:
        return await self._record_delivery_sent(
            tenant_id,
            event_id,
            message_id=message_id,
            sent_at=sent_at,
            message_key="group_message_id",
            sent_at_key="group_message_sent_at",
        )

    async def _record_delivery_sent(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        message_id: str,
        sent_at: datetime,
        message_key: str,
        sent_at_key: str,
    ) -> bool:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                SampleNotificationOutbox, event_id, with_for_update=True
            )
            if event is None or event.status != "processing":
                return False
            payload = dict(event.payload)
            payload[message_key] = message_id
            payload[sent_at_key] = sent_at.astimezone(UTC).isoformat()
            event.payload = payload
            await session.commit()
            return True
        return False

    async def succeed(
        self, tenant_id: UUID, event_id: UUID, *, sent_at: datetime
    ) -> None:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                SampleNotificationOutbox, event_id, with_for_update=True
            )
            if event is None or event.status != "processing":
                return
            event.status = "sent"
            event.sent_at = sent_at.astimezone(UTC)
            event.next_attempt_at = None
            event.last_error_code = None
            event.last_error_summary = None
            await session.commit()
            return

    async def fail(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        code: str,
        summary: str,
        retry_at: datetime | None,
    ) -> None:
        async for session in self._database.session(tenant_id):
            event = await session.get(
                SampleNotificationOutbox, event_id, with_for_update=True
            )
            if event is None or event.status != "processing":
                return
            event.status = "retry_wait" if retry_at else "failed"
            event.next_attempt_at = retry_at
            event.last_error_code = code[:64]
            event.last_error_summary = summary[:1000]
            await session.commit()
            return

    async def requeue_unavailable_recipient(
        self,
        tenant_id: UUID,
        event_id: UUID,
        *,
        now: datetime,
    ) -> bool:
        if now.tzinfo is None:
            raise ValueError("Notification retry time must include a timezone.")
        async for session in self._database.session(tenant_id):
            event = await session.get(
                SampleNotificationOutbox, event_id, with_for_update=True
            )
            payload = event.payload if event is not None else None
            if (
                event is None
                or event.status != "failed"
                or event.last_error_code != "230013"
                or event.sent_at is not None
                or not isinstance(payload, dict)
                or payload.get("message_id") is not None
            ):
                return False
            event.status = "pending"
            event.attempt_count = 0
            event.next_attempt_at = now.astimezone(UTC)
            event.last_error_code = None
            event.last_error_summary = None
            await session.commit()
            return True
        return False

    async def requeue_current_failures(self, *, now: datetime) -> int:
        if now.tzinfo is None:
            raise ValueError("Notification reconciliation time must include a timezone.")
        eligible = (
            select(SampleNotificationOutbox.id)
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id
                == SampleNotificationOutbox.sample_application_id,
            )
            .join(
                SampleApplication,
                SampleApplication.id == SampleNotificationOutbox.sample_application_id,
            )
            .where(
                SampleNotificationOutbox.status == "failed",
                SampleNotificationOutbox.assignment_version
                == SampleApplicationWorkflow.assignment_version,
                SampleApplicationWorkflow.assigned_bd_name.is_not(None),
                SampleApplicationWorkflow.feishu_record_id.is_not(None),
                SampleApplication.is_current_projection.is_(True),
            )
        )
        statement = (
            update(SampleNotificationOutbox)
            .where(SampleNotificationOutbox.id.in_(eligible))
            .values(
                status="pending",
                attempt_count=0,
                next_attempt_at=now.astimezone(UTC),
                last_error_code=None,
                last_error_summary=None,
            )
            .returning(SampleNotificationOutbox.id)
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
            await session.commit()
        return len(rows)
