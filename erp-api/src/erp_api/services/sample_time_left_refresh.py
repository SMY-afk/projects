"""Refresh existing sample countdown cells independently of source capture."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.shop import Shop
from erp_api.services.feishu_sample_record_snapshot import parse_feishu_record_snapshot
from erp_api.services.sample_feishu_mapper import format_sample_time_left
from erp_api.services.sample_remaining_display import sample_remaining_display

FIELD_NAME = "样品申请剩余时间"
SYNC_KEY_FIELD = "同步键（系统）"
logger = logging.getLogger(__name__)


def field_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(
        isinstance(item, dict) and isinstance(item.get("text"), str) for item in value
    ):
        return "".join(item["text"] for item in value)
    return ""


async def _read_records(client, record_ids, *, allow_missing=False):
    data = await client._request(
        "POST",
        f"{client._record_path()}/batch_get",
        token=await client.tenant_access_token(),
        retry_mode="idempotent",
        json={"record_ids": list(record_ids)},
    )
    items = data.get("records")
    if not isinstance(items, list):
        raise TypeError("Sample countdown read response is incomplete.")
    snapshots = {}
    for item in items:
        record_id = item.get("record_id") if isinstance(item, dict) else None
        if record_id not in record_ids or record_id in snapshots:
            raise RuntimeError("Sample countdown read identity mismatch.")
        snapshots[record_id] = parse_feishu_record_snapshot(item).fields
    if not allow_missing and set(snapshots) != set(record_ids):
        raise RuntimeError("Sample countdown read response is incomplete.")
    return snapshots


async def refresh_time_left_records(client, desired) -> int:
    updated_count = 0
    ids = tuple(desired)
    for offset in range(0, len(ids), 100):
        batch_ids = ids[offset : offset + 100]
        actual = await _read_records(client, batch_ids, allow_missing=True)
        missing_ids = set(batch_ids) - set(actual)
        if missing_ids:
            logger.warning(
                "sample_countdown_missing_records count=%s", len(missing_ids)
            )
        updates = []
        for record_id in batch_ids:
            if record_id not in actual:
                continue
            sync_key, desired_fields = desired[record_id]
            if field_text(actual[record_id].get(SYNC_KEY_FIELD)) != sync_key:
                raise RuntimeError("Sample countdown saved record identity mismatch.")
            changes = {
                name: value
                for name, value in desired_fields.items()
                if field_text(actual[record_id].get(name)) != value
            }
            if changes:
                updates.append((record_id, changes))
        if not updates:
            continue
        await client.batch_update_records(updates)
        readback = await _read_records(client, tuple(row[0] for row in updates))
        if any(
            field_text(readback[record_id].get(name)) != value
            for record_id, fields in updates
            for name, value in fields.items()
        ):
            raise RuntimeError("Sample countdown write readback mismatch.")
        updated_count += len(updates)
    return updated_count


async def list_time_left_targets(database, shop_ids):
    statement = (
        select(
            SampleApplication.tenant_id,
            SampleApplication.shop_id,
            SampleApplication.platform_application_id,
            SampleApplication.approve_expiration_at,
            SampleApplicationWorkflow.feishu_record_id,
            SampleApplication.platform_status,
            SampleApplication.is_current_projection,
            SampleApplication.raw_payload,
        )
        .join(
            SampleApplicationWorkflow,
            and_(
                SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
                SampleApplicationWorkflow.tenant_id == SampleApplication.tenant_id,
                SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
            ),
        )
        .join(
            SampleIngestBatch,
            SampleIngestBatch.id == SampleApplication.source_capture_id,
        )
        .join(
            Shop,
            and_(
                Shop.id == SampleApplication.shop_id,
                Shop.tenant_id == SampleApplication.tenant_id,
            ),
        )
        .where(
            SampleApplication.shop_id.in_(shop_ids),
            or_(
                and_(
                    SampleApplication.platform_status == "PENDING",
                    SampleApplication.is_current_projection.is_(True),
                ),
                and_(
                    Shop.shop_name == "fanfu toy tool",
                    SampleApplicationWorkflow.assigned_bd_name.is_not(None),
                ),
            ),
            SampleApplicationWorkflow.feishu_record_id.is_not(None),
            SampleIngestBatch.status == "complete",
        )
        .order_by(SampleApplication.shop_id, SampleApplication.id)
    )
    async with database.system_session_factory() as session:
        return (await session.execute(statement)).all()


def build_desired_time_left(rows, *, now: datetime | None = None):
    current = now or datetime.now(UTC)
    grouped = {}
    for (
        tenant_id,
        shop_id,
        application_id,
        deadline,
        record_id,
        status,
        is_current,
        raw,
    ) in rows:
        records = grouped.setdefault((tenant_id, shop_id), {})
        fields = {
            FIELD_NAME: sample_remaining_display(
                status=status,
                is_current=is_current,
                deadline=deadline,
                now=current,
                format_time=format_sample_time_left,
            )
        }
        if isinstance(raw, dict) and raw.get("status") == status:
            fields["TK申请状态"] = status
        desired = (
            f"{shop_id}:{application_id}",
            fields,
        )
        if record_id in records and records[record_id] != desired:
            raise RuntimeError("Sample countdown record mapping is ambiguous.")
        records[record_id] = desired
    return grouped
