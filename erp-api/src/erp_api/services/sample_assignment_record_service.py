from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.refundable_identity_guard import refundable_identity_condition
from erp_api.services.sample_assignment_record_fields import (
    creator_record_key,
    record_fields,
)
from erp_api.services.sample_assignment_record_guard import (
    validate_assignment_record_update,
)

logger = logging.getLogger("erp_api.assignment_record")


@dataclass(frozen=True)
class SampleAssignmentRecordResult:
    created_count: int
    updated_count: int


class SampleAssignmentRecordService:
    def __init__(
        self,
        database: Database,
        client,
        *,
        activation_at: datetime,
        limit: int = 100,
        change_notifier: Callable[[], Awaitable[object]] | None = None,
        sample_type: str = "free",
    ) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Sample assignment record limit is invalid.")
        if activation_at.utcoffset() is None:
            raise ValueError("Sample assignment record activation time is invalid.")
        self._database = database
        self._client = client
        self._activation_at = activation_at.astimezone(UTC)
        self._limit = limit
        self._change_notifier = change_notifier
        self._sample_type = sample_type

    async def sync(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        outbox_ids: frozenset[UUID] | None = None,
        application_ids: frozenset[UUID] | None = None,
    ) -> SampleAssignmentRecordResult:
        if outbox_ids is not None and application_ids is not None:
            raise ValueError("Assignment record target scopes are mutually exclusive.")
        targets = await self._list_targets(
            tenant_id,
            shop_id,
            outbox_ids,
            application_ids,
        )
        missing_record_id = any(
            _stored_assignment_record_id(target[0]) is None for target in targets
        )
        if missing_record_id:
            (
                existing,
                creator_records,
                duplicate_numbers,
                duplicate_creators,
            ) = await self._existing_records()
            if self._sample_type == "refundable":
                creator_records, duplicate_creators = {}, frozenset()
        else:
            existing, creator_records = {}, {}
            duplicate_numbers = duplicate_creators = frozenset()
        processed_creators: set[tuple[str, str]] = set()
        planned = []
        for target in targets:
            stored_record_id = _stored_assignment_record_id(target[0])
            if target[0].status == "cancelled" and stored_record_id is None:
                continue
            fields = record_fields(target)
            creator_key = (
                (str(target[1].platform_application_id), str(shop_id))
                if self._sample_type == "refundable" else creator_record_key(fields)
            )
            if creator_key in processed_creators:
                continue
            processed_creators.add(creator_key)
            planned.append((target[0], fields))
        created, updated = await self._write_targets(
            tenant_id=tenant_id,
            shop_id=shop_id,
            planned=planned,
            existing=existing,
            creator_records=creator_records,
            duplicate_numbers=duplicate_numbers,
            duplicate_creators=duplicate_creators,
        )
        if (created or updated) and self._change_notifier is not None:
            try:
                await self._change_notifier()
            except Exception:
                logger.exception("Assignment summary change notification failed")
        return SampleAssignmentRecordResult(created, updated)

    async def _write_targets(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        planned,
        existing: dict[str, str],
        creator_records: dict[tuple[str, str], str],
        duplicate_numbers: frozenset[str],
        duplicate_creators: frozenset[tuple[str, str]],
    ) -> tuple[int, int]:
        if not planned:
            return 0, 0
        creates = []
        updates = []
        bindings = []
        async with self._database.system_session_factory() as session:
            for outbox, fields in sorted(planned, key=lambda item: item[0].id):
                statement = (
                    select(SampleNotificationOutbox)
                    .where(
                        SampleNotificationOutbox.id == outbox.id,
                        SampleNotificationOutbox.tenant_id == tenant_id,
                        SampleNotificationOutbox.shop_id == shop_id,
                        or_(
                            SampleNotificationOutbox.status != "cancelled",
                            SampleNotificationOutbox.payload[
                                "assignment_record_id"
                            ].astext.is_not(None),
                        ),
                    )
                    .with_for_update()
                )
                locked = await session.scalar(statement)
                if locked is None:
                    raise RuntimeError("Assignment record outbox is unavailable.")
                record_id = _stored_assignment_record_id(locked)
                if record_id is None:
                    number = str(fields["分配编号"])
                    creator_key = creator_record_key(fields)
                    if number in duplicate_numbers:
                        raise RuntimeError(
                            "Feishu assignment record identity is duplicated."
                        )
                    if creator_key in duplicate_creators:
                        raise RuntimeError(
                            "Feishu assignment record creator and shop is duplicated; "
                            "manual review is required before deletion."
                        )
                    record_id = existing.get(number) or creator_records.get(creator_key)
                    if record_id is None:
                        creates.append((outbox, locked, fields))
                        continue
                    bindings.append((outbox, locked, record_id))
                else:
                    outbox.payload = dict(locked.payload or {})
                current_fields = await self._client.get_record(record_id)
                validate_assignment_record_update(current_fields, fields)
                updates.append((record_id, fields))
            if creates:
                created = await self._client.batch_create_assignment_records(
                    [fields for _outbox, _locked, fields in creates]
                )
                for outbox, locked, fields in creates:
                    bindings.append((outbox, locked, created[str(fields["分配编号"])]))
            for outbox, locked, record_id in bindings:
                payload = dict(locked.payload or {})
                payload["assignment_record_id"] = record_id
                locked.payload = payload
                outbox.payload = payload
            if bindings:
                await session.commit()
        if updates:
            await self._client.batch_update_assignment_records(updates)
        return len(creates), len(updates)

    async def _list_targets(
        self,
        tenant_id,
        shop_id,
        outbox_ids,
        application_ids,
    ):
        statement = (
            select(
                SampleNotificationOutbox,
                SampleApplication,
                SampleApplicationWorkflow,
                Shop,
            )
            .join(
                SampleApplication,
                SampleApplication.id == SampleNotificationOutbox.sample_application_id,
            )
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id
                == SampleNotificationOutbox.sample_application_id,
            )
            .join(
                Shop,
                and_(
                    Shop.id == SampleApplication.shop_id,
                    Shop.tenant_id == SampleApplication.tenant_id,
                ),
            )
            .where(
                SampleNotificationOutbox.tenant_id == tenant_id,
                SampleNotificationOutbox.shop_id == shop_id,
                SampleApplication.sample_type == self._sample_type,
                SampleNotificationOutbox.payload["source_event_id"].astext.like(
                    "bd-auto:%"
                ),
                or_(
                    SampleNotificationOutbox.status != "cancelled",
                    SampleNotificationOutbox.payload[
                        "assignment_record_id"
                    ].astext.is_not(None),
                ),
                SampleNotificationOutbox.assignment_version
                == SampleApplicationWorkflow.assignment_version,
                SampleApplicationWorkflow.assigned_bd_name.is_not(None),
                SampleApplication.is_current_projection.is_(True),
                refundable_identity_condition(SampleApplication),
                SampleApplication.raw_payload["manual_assignment_deleted"]
                .as_boolean()
                .is_not(True),
                or_(
                    and_(SampleApplication.sample_type == "refundable",
                         SampleApplication.first_seen_at >= self._activation_at),
                    and_(
                        SampleApplication.source_type == "hubstudio_cdp",
                        SampleApplication.tiktok_applied_at >= self._activation_at,
                    ),
                    and_(
                        SampleApplication.source_type == "official_api",
                        SampleApplication.first_seen_at >= self._activation_at,
                    ),
                ),
            )
            .order_by(SampleNotificationOutbox.created_at.desc())
            .limit(self._limit)
        )
        if outbox_ids is not None:
            statement = statement.where(SampleNotificationOutbox.id.in_(outbox_ids))
        elif application_ids is not None:
            statement = statement.where(SampleApplication.id.in_(application_ids))
        async with self._database.system_session_factory() as session:
            return tuple((await session.execute(statement)).all())

    async def _existing_records(
        self,
    ) -> tuple[
        dict[str, str],
        dict[tuple[str, str], str],
        frozenset[str],
        frozenset[tuple[str, str]],
    ]:
        records = await self._client.list_record_snapshots()
        assignment_groups: dict[str, list] = {}
        grouped: dict[tuple[str, str], list] = {}
        for record in records:
            number = record.snapshot.fields.get("分配编号")
            if not isinstance(number, str) or not number.strip():
                continue
            assignment_groups.setdefault(number, []).append(record)
            key = creator_record_key(record.snapshot.fields)
            if all(key):
                grouped.setdefault(key, []).append(record)
        existing = {
            number: matches[0].record_id
            for number, matches in assignment_groups.items()
            if len(matches) == 1
        }
        creator_records = {
            key: matches[0].record_id
            for key, matches in grouped.items()
            if len(matches) == 1
        }
        return (
            existing,
            creator_records,
            frozenset(
                number
                for number, matches in assignment_groups.items()
                if len(matches) > 1
            ),
            frozenset(key for key, matches in grouped.items() if len(matches) > 1),
        )


def _stored_assignment_record_id(outbox) -> str | None:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    value = payload.get("assignment_record_id")
    return value.strip() if isinstance(value, str) and value.strip() else None
