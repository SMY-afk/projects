from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

_VOLATILE_FIELDS = frozenset({"首次同步时间", "最近同步时间", "通知状态", "通知时间"})
_AUDIT_INTERVAL = timedelta(hours=24)


def system_fields_hash(fields: Mapping[str, object]) -> str:
    stable = {
        key: value for key, value in fields.items() if key not in _VOLATILE_FIELDS
    }
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recently_synced(record: object, desired_hash: str, *, now: datetime) -> bool:
    last_sync_at = getattr(record, "last_sync_at", None)
    return (
        bool(getattr(record, "feishu_record_id", None))
        and getattr(record, "sync_status", None) == "succeeded"
        and getattr(record, "sync_hash", None) == desired_hash
        and isinstance(last_sync_at, datetime)
        and last_sync_at.tzinfo is not None
        and timedelta()
        <= now.astimezone(UTC) - last_sync_at.astimezone(UTC)
        < _AUDIT_INTERVAL
    )
