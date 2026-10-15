from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS


@dataclass(frozen=True)
class FeishuSampleChange:
    actor_id: str
    actor_name: str
    modified_at: datetime
    business_fields: dict[str, Any]


@dataclass(frozen=True)
class FeishuBusinessFieldPatch:
    fields: dict[str, str | None]
    assignment_recipient_open_id: str | None = None


@dataclass(frozen=True)
class FeishuAssignee:
    open_id: str | None
    name: str | None


def filter_feishu_business_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Copy only user-owned fields and preserve partial-update semantics."""
    return {name: fields[name] for name in BUSINESS_FIELDS if name in fields}


def normalize_feishu_business_field(field_name: str, value: object) -> str | None:
    if field_name not in BUSINESS_FIELDS:
        raise ValueError("Feishu business field is not allowed.")
    if value is None or value == []:
        return None
    if field_name == "分配BD":
        return parse_feishu_assignee(value).name
    if not isinstance(value, str):
        raise TypeError("Feishu business field value is invalid.")
    normalized = value.strip()
    if field_name == "处理状态" and len(normalized) > 64:
        raise ValueError("Feishu processing status is too long.")
    if field_name == "分配BD" and len(normalized) > 255:
        raise ValueError("Feishu BD name is too long.")
    return normalized or None


def parse_feishu_assignee(value: object) -> FeishuAssignee:
    if value is None or value == []:
        return FeishuAssignee(None, None)
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError("Feishu BD assignment must contain one user.")
        value = value[0]
    if isinstance(value, str):
        return FeishuAssignee(None, value.strip() or None)
    if not isinstance(value, dict):
        raise TypeError("Feishu BD assignment is invalid.")
    open_id = value.get("id")
    name = value.get("name")
    if not isinstance(open_id, str) or not open_id.strip():
        raise ValueError("Feishu BD assignment has no user ID.")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Feishu BD assignment has no user name.")
    return FeishuAssignee(open_id.strip(), name.strip())


def normalize_feishu_business_fields(
    fields: dict[str, Any], field_names: set[str]
) -> FeishuBusinessFieldPatch:
    normalized: dict[str, str | None] = {}
    recipient_open_id: str | None = None
    for field_name in field_names:
        value = fields.get(field_name)
        if field_name == "分配BD":
            assignee = parse_feishu_assignee(value)
            normalized[field_name] = assignee.name
            recipient_open_id = assignee.open_id
        else:
            normalized[field_name] = normalize_feishu_business_field(field_name, value)
    return FeishuBusinessFieldPatch(normalized, recipient_open_id)


def parse_feishu_sample_change(fields: dict[str, Any]) -> FeishuSampleChange:
    actor = fields.get("最后修改人")
    modified_time = fields.get("最后修改时间")
    if not isinstance(actor, dict):
        raise TypeError("Feishu record has no last modifier metadata.")
    actor_id = actor.get("id")
    actor_name = actor.get("name")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError("Feishu last modifier has no id.")
    if not isinstance(actor_name, str) or not actor_name:
        raise ValueError("Feishu last modifier has no name.")
    if not isinstance(modified_time, int) or isinstance(modified_time, bool):
        raise TypeError("Feishu record has no last modified time.")
    return FeishuSampleChange(
        actor_id=actor_id,
        actor_name=actor_name,
        modified_at=datetime.fromtimestamp(modified_time / 1000, tz=UTC),
        business_fields=filter_feishu_business_fields(fields),
    )
