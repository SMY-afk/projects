from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from erp_api.services.feishu_bd_roster_provider import (
    BD_NAME_FIELD,
    BD_PERSON_FIELD,
    BD_STATUS_FIELD,
)
from erp_api.services.feishu_creator_export_service import FEISHU_CREATOR_FIELDS
from erp_api.services.sample_cooperation_parsing import (
    is_current_bd_owner,
    plain_text,
    split_bd_owners,
)
from erp_api.services.sample_cooperation_rules import (
    CooperationRecipient,
    CooperationRow,
    CooperationSnapshot,
    normalize_account_name,
    normalize_bd_name,
)

DAILY_VALID_CREATORS_TABLE_ID = "tblexample97f4b43d"
DAILY_VALID_CREATOR_ACCOUNT_FIELD = "账号名称"
DAILY_VALID_CREATOR_FIELDS = (
    DAILY_VALID_CREATOR_ACCOUNT_FIELD, "BD负责人", "匹配店铺", "保留原因",
)


@dataclass(frozen=True)
class CooperationTableClient:
    label: str
    client: object
    view_id: str


class SampleCooperationReader:
    def __init__(
        self,
        tables: tuple[CooperationTableClient, ...],
        roster_client,
        valid_creator_client,
        invitation_protection=None,
        *,
        ai_invitation_client=None,
    ) -> None:
        if len(tables) != 2:
            raise ValueError("Sample cooperation precheck requires exactly two tables.")
        self._tables = tables
        self._roster = roster_client
        self._valid_creators = valid_creator_client
        self._invitation_protection = invitation_protection
        self._ai_invitations = ai_invitation_client

    async def read(
        self,
        *,
        creator_ids: frozenset[str] = frozenset(),
    ) -> CooperationSnapshot:
        tasks = [
            *(
                table.client.list_record_snapshots(
                    view_id=table.view_id,
                    field_names=FEISHU_CREATOR_FIELDS,
                )
                for table in self._tables
            ),
            self._valid_creators.list_record_snapshots(
                field_names=DAILY_VALID_CREATOR_FIELDS,
            ),
            self._roster.list_record_snapshots(),
        ]
        if self._invitation_protection is not None:
            tasks.append(self._invitation_protection.refresh())
        if self._ai_invitations is not None:
            tasks.append(
                self._ai_invitations.match_creator_ids(
                    creator_ids,
                    field_name="达人ID",
                )
            )
        results = await asyncio.gather(*tasks)
        if self._invitation_protection is not None:
            pending_ids = results[len(self._tables) + 2].pending_creator_ids
            if pending_ids & frozenset(normalize_account_name(value) for value in creator_ids):
                raise RuntimeError("AI invitation time requires verification for current creator.")
        cooperation_results = results[: len(self._tables)]
        valid_creator_records = results[len(self._tables)]
        roster_records = results[len(self._tables) + 1]
        protected_creators = (
            results[len(self._tables) + 2].active
            if self._invitation_protection is not None
            else {}
        )
        ai_result_index = len(self._tables) + 2 + int(
            self._invitation_protection is not None
        )
        ai_invitation_creator_ids = (
            results[ai_result_index] if self._ai_invitations is not None else frozenset()
        )
        rows = tuple(
            CooperationRow(
                source=table.label,
                record_id=record.record_id,
                account_name=record.snapshot.fields.get(FEISHU_CREATOR_FIELDS[0]),
                bd_owner=record.snapshot.fields.get(FEISHU_CREATOR_FIELDS[1]),
                approved_date=record.snapshot.fields.get(FEISHU_CREATOR_FIELDS[2]),
            )
            for table, records in zip(self._tables, cooperation_results, strict=True)
            for record in records
        )
        current_names = _roster_names(roster_records)
        daily_rows = tuple(CooperationRow(
            source=plain_text(record.snapshot.fields.get("匹配店铺")),
            record_id=record.record_id,
            account_name=record.snapshot.fields.get(DAILY_VALID_CREATOR_ACCOUNT_FIELD),
            bd_owner=record.snapshot.fields.get("BD负责人"), approved_date=None,
        ) for record in valid_creator_records
            if not plain_text(record.snapshot.fields.get("保留原因")).startswith(
                ("历史留存", "待核验")))
        valid_creator_ids = frozenset(normalize_account_name(row.account_name)
            for row in daily_rows if any(is_current_bd_owner(owner, current_names)
                for owner in split_bd_owners(row.bd_owner))) - {""}
        return CooperationSnapshot(
            rows=rows,
            recipients=_roster_recipients(roster_records),
            current_bd_names=current_names,
            valid_creator_ids=valid_creator_ids,
            ai_invitation_creator_ids=ai_invitation_creator_ids,
            protected_creators=protected_creators,
            daily_valid_rows=daily_rows,
        )

    async def resolve_current_recipient(
        self, recipient: CooperationRecipient
    ) -> CooperationRecipient | None:
        records = await self._roster.list_record_snapshots()
        matches = [
            record
            for record in records
            if _text(record.snapshot.fields.get(BD_NAME_FIELD)) == recipient.name
            and _text(record.snapshot.fields.get(BD_STATUS_FIELD)) == "在岗"
        ]
        if len(matches) != 1:
            return None
        return _roster_recipients(records).get(normalize_bd_name(recipient.name))


def _roster_recipients(records) -> dict[str, CooperationRecipient]:
    recipients: dict[str, CooperationRecipient] = {}
    ambiguous: set[str] = set()
    people_names: dict[str, set[str]] = {}
    for record in records:
        fields = record.snapshot.fields
        if _text(fields.get(BD_STATUS_FIELD)) != "在岗":
            continue
        name = _text(fields.get(BD_NAME_FIELD))
        normalized = normalize_bd_name(name)
        open_id = _person_open_id(fields.get(BD_PERSON_FIELD))
        if not normalized or not name or not open_id:
            continue
        existing = recipients.get(normalized)
        if existing is not None and existing.open_id != open_id:
            ambiguous.add(normalized)
            continue
        recipients[normalized] = CooperationRecipient(name, open_id)
        people_names.setdefault(open_id, set()).add(normalized)
    for names in people_names.values():
        if len(names) > 1:
            ambiguous.update(names)
    for normalized in ambiguous:
        recipients.pop(normalized, None)
    return recipients


def _roster_names(records) -> frozenset[str]:
    return frozenset(
        normalized
        for record in records
        if _text(record.snapshot.fields.get(BD_STATUS_FIELD)) == "在岗"
        if (normalized := normalize_bd_name(record.snapshot.fields.get(BD_NAME_FIELD)))
    )


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list) and len(value) == 1:
        return _text(value[0])
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("text") or value.get("value"))
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
