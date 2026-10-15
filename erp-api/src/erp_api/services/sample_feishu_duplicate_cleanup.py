from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID


def find_duplicate_record_ids(
    desired_records: Sequence[tuple[str, object]],
    existing: Mapping[str, str],
    remote_fields: Mapping[str, Mapping[str, object]],
    *,
    started_at: datetime,
) -> tuple[str, ...]:
    if started_at.utcoffset() is None:
        raise ValueError("Feishu deduplication start time must include a timezone.")
    cutoff = started_at.astimezone(UTC)
    desired_by_creator: dict[str, str] = {}
    desired_keys: set[str] = set()
    for sync_key, record in desired_records:
        desired_keys.add(sync_key)
        creator_key = _source_creator_key(record)
        if not creator_key:
            continue
        existing_key = desired_by_creator.get(creator_key)
        if existing_key not in (None, sync_key):
            raise RuntimeError(
                "PostgreSQL current sample creator identity is duplicated."
            )
        desired_by_creator[creator_key] = sync_key

    obsolete: list[str] = []
    for sync_key, record_id in existing.items():
        if sync_key in desired_keys:
            continue
        fields = remote_fields.get(record_id, {})
        applied_at = _remote_applied_at(fields.get("TikTok申请时间"))
        if applied_at is None or applied_at < cutoff:
            continue
        creator_key = _remote_creator_key(fields)
        if creator_key and creator_key in desired_by_creator:
            obsolete.append(record_id)
    return tuple(obsolete)


async def delete_duplicate_records(
    desired_records: Sequence[tuple[str, object]],
    existing: dict[str, str],
    remote_fields: dict[str, dict[str, object]],
    *,
    started_at: datetime,
    feishu,
    mappings,
    tenant_id: UUID,
    shop_id: UUID,
    batch_size: int,
    allow_delete: bool = False,
) -> int:
    if not allow_delete:
        raise RuntimeError(
            "Feishu duplicate deletion requires explicit manual approval."
        )
    obsolete_ids = find_duplicate_record_ids(
        desired_records,
        existing,
        remote_fields,
        started_at=started_at,
    )
    deleted_count = 0
    for offset in range(0, len(obsolete_ids), batch_size):
        batch = list(obsolete_ids[offset : offset + batch_size])
        deleted = list(await feishu.batch_delete_records(batch))
        await mappings.detach_records(
            tenant_id=tenant_id,
            shop_id=shop_id,
            record_ids=deleted,
        )
        deleted_set = set(deleted)
        for sync_key, record_id in tuple(existing.items()):
            if record_id in deleted_set:
                del existing[sync_key]
        for record_id in deleted:
            remote_fields.pop(record_id, None)
        deleted_count += len(deleted)
    return deleted_count


def _source_creator_key(record: object) -> str:
    if getattr(record, "sample_type", "free") == "refundable":
        return f"refundable:application:{record.platform_application_id}"
    username = _username(getattr(record, "creator_username", None))
    if username:
        return f"username:{username}"
    creator_open_id = _text(getattr(record, "creator_open_id", None))
    return f"open:{creator_open_id}" if creator_open_id else ""


def _remote_creator_key(fields: Mapping[str, object]) -> str:
    if fields.get("样品类型") == "买返样品":
        return f"refundable:application:{fields.get('申请编号', '')}"
    username = _username(fields.get("达人账号"))
    if username:
        return f"username:{username}"
    creator_open_id = _text(fields.get("达人OpenID"))
    return f"open:{creator_open_id}" if creator_open_id else ""


def _remote_applied_at(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _username(value: object) -> str:
    return _text(value).lstrip("@").casefold()
