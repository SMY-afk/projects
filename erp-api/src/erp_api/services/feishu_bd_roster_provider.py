from __future__ import annotations

import re
from collections.abc import Collection
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_bd_assignment import BdWorkload

BD_NAME_FIELD = "BD姓名"
BD_PERSON_FIELD = "飞书人员"
BD_CATEGORY_FIELD = "负责品类"
BD_STATUS_FIELD = "在岗状态"
BD_PENDING_FIELD = "当前待处理量"
REQUIRED_ROSTER_FIELDS = frozenset(
    {
        BD_NAME_FIELD,
        BD_PERSON_FIELD,
        BD_CATEGORY_FIELD,
        BD_STATUS_FIELD,
        BD_PENDING_FIELD,
    }
)


class FeishuBdRosterProvider:
    def __init__(
        self,
        client: FeishuSampleBatchClient,
        *,
        allowed_bd_names: Collection[str],
        default_capacity: int,
        assignment_workloads=None,
    ) -> None:
        names = frozenset(name.strip() for name in allowed_bd_names if name.strip())
        if not names:
            raise ValueError("BD roster requires explicit allowed names.")
        if default_capacity <= 0:
            raise ValueError("BD capacity must be positive.")
        self._client = client
        self._allowed_bd_names = names
        self._default_capacity = default_capacity
        self._assignment_workloads = assignment_workloads

    async def list_members(
        self, tenant_id: UUID, shop_id: UUID, *, sample_type: str = "free"
    ) -> tuple[BdWorkload, ...]:
        if sample_type not in {"free", "refundable"}:
            raise ValueError("BD roster sample type is invalid")
        roster = await self._list_configured_members()
        if self._assignment_workloads is None:
            return roster
        return await self._assignment_workloads.enrich(
            shop_id, roster, sample_type=sample_type
        )

    async def list_recipient_open_ids(self) -> dict[str, str]:
        members = await self._list_configured_members()
        return {
            member.name: member.recipient_open_id
            for member in members
            if member.recipient_open_id
        }

    async def _list_configured_members(self) -> tuple[BdWorkload, ...]:
        metadata = await self._client.validate_required_fields(REQUIRED_ROSTER_FIELDS)
        if metadata[BD_PERSON_FIELD].field_type != 11:
            raise ValueError("Feishu BD person field must use the person field type.")
        records = await self._client.list_record_snapshots()
        members = []
        for record in records:
            fields = record.snapshot.fields
            name = _text(fields.get(BD_NAME_FIELD))
            if name not in self._allowed_bd_names:
                continue
            members.append(
                BdWorkload(
                    name=name,
                    bd_id=record.record_id,
                    recipient_open_id=_person_open_id(fields.get(BD_PERSON_FIELD)),
                    categories=_categories(fields.get(BD_CATEGORY_FIELD)),
                    current_pending=_nonnegative_int(fields.get(BD_PENDING_FIELD)),
                    capacity=self._default_capacity,
                    active=_text(fields.get(BD_STATUS_FIELD)) == "在岗",
                )
            )
        found_names = {member.name for member in members}
        if found_names != self._allowed_bd_names:
            missing = sorted(self._allowed_bd_names - found_names)
            raise ValueError(
                "Feishu BD roster is missing configured members: " + ", ".join(missing)
            )
        return tuple(members)


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list) and len(value) == 1:
        item = value[0]
        if isinstance(item, str):
            return item.strip() or None
        if isinstance(item, dict):
            text = item.get("text") or item.get("name")
            return text.strip() if isinstance(text, str) and text.strip() else None
    return None


def _person_open_id(value: Any) -> str | None:
    people = value if isinstance(value, list) else [value]
    if len(people) != 1 or not isinstance(people[0], dict):
        return None
    identifier = people[0].get("id") or people[0].get("open_id")
    return (
        identifier.strip()
        if isinstance(identifier, str) and identifier.strip()
        else None
    )


def _categories(value: Any) -> frozenset[str]:
    if isinstance(value, list):
        values = [_text(item) for item in value]
    else:
        text = _text(value)
        values = re.split(r"[,，;/；]", text) if text else []
    categories = frozenset(item.strip() for item in values if item and item.strip())
    return categories or frozenset({"*"})


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Feishu BD pending count is invalid.") from None
    if number < 0 or number != number.to_integral_value():
        raise ValueError("Feishu BD pending count is invalid.")
    return int(number)
