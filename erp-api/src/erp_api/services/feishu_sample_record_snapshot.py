from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from erp_api.services.feishu_sample_errors import FeishuSampleError


@dataclass(frozen=True)
class FeishuRecordSnapshot:
    fields: dict[str, Any]
    creator_id: str | None = None
    creator_name: str | None = None
    modifier_id: str | None = None
    modifier_name: str | None = None
    modified_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class FeishuListedRecord:
    record_id: str
    snapshot: FeishuRecordSnapshot


def parse_feishu_record_snapshot(record: object) -> FeishuRecordSnapshot:
    fields = record.get("fields") if isinstance(record, dict) else None
    if not isinstance(fields, dict):
        raise FeishuSampleError("Feishu record response is missing fields.")
    creator = record.get("created_by")
    modifier = record.get("last_modified_by")
    return FeishuRecordSnapshot(
        fields=fields,
        creator_id=_optional_text(creator, "id"),
        creator_name=_optional_text(creator, "name"),
        modifier_id=_optional_text(modifier, "id"),
        modifier_name=_optional_text(modifier, "name"),
        modified_at=_optional_millisecond_time(record.get("last_modified_time")),
        created_at=_optional_millisecond_time(record.get("created_time")),
    )


def _optional_text(value: object, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    item = value.get(key)
    return item if isinstance(item, str) and item else None


def _optional_millisecond_time(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value) if isinstance(value, (int, str)) else None
        if timestamp is None or timestamp < 0:
            return None
        return datetime.fromtimestamp(timestamp / 1000, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
