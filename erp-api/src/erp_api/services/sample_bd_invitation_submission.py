from __future__ import annotations

import re

from erp_api.services.sample_bd_invitation_parsing import (
    requires_creator_id_expansion,
    split_creator_ids,
)
from erp_api.services.sample_cooperation_parsing import plain_text

BD_INVITATION_CREATOR_FIELD = "达人ID"
BD_INVITATION_OWNER_FIELD = "BD负责人"
BD_INVITATION_REMARK_FIELD = "备注"
BD_INVITATION_ORIGINAL_SUBMITTER_FIELD = "原提交人"
BD_INVITATION_FORM_ENTRY_CREATOR = "👉 请点击“BD填写入口”链接填写"
_FORM_ENTRY_COMPACT = re.sub(r"\s+", "", BD_INVITATION_FORM_ENTRY_CREATOR).casefold()


def business_records(records) -> tuple:
    return tuple(
        record
        for record in records
        if re.sub(
            r"\s+",
            "",
            plain_text(record.snapshot.fields.get(BD_INVITATION_CREATOR_FIELD)),
        ).casefold()
        != _FORM_ENTRY_COMPACT
    )


async def split_batch_submissions(client, records) -> bool:
    updates: list[tuple[str, str, str]] = []
    creates: list[tuple[str, str, str]] = []
    for record in records:
        raw_value = plain_text(record.snapshot.fields.get(BD_INVITATION_CREATOR_FIELD))
        creator_ids = split_creator_ids(raw_value)
        if len(creator_ids) <= 1 and not requires_creator_id_expansion(raw_value):
            continue
        if not creator_ids:
            raise RuntimeError(
                "BD invitation protection record requires at least one creator ID."
            )
        bd_name = plain_text(record.snapshot.fields.get(BD_INVITATION_OWNER_FIELD))
        if not bd_name:
            raise RuntimeError("BD invitation protection record requires a BD owner.")
        original_submitter = plain_text(
            record.snapshot.fields.get(BD_INVITATION_ORIGINAL_SUBMITTER_FIELD)
        ) or plain_text(record.snapshot.creator_name)
        if not original_submitter:
            raise RuntimeError(
                "BD invitation protection record requires an original submitter."
            )
        updates.append((record.record_id, creator_ids[0], original_submitter))
        creates.extend(
            (creator_id, bd_name, original_submitter) for creator_id in creator_ids[1:]
        )
    for offset in range(0, len(updates), 500):
        await client.batch_update_split_records(updates[offset : offset + 500])
    for offset in range(0, len(creates), 500):
        await client.batch_create_invitations(creates[offset : offset + 500])
    return bool(updates or creates)
