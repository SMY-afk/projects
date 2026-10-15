from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict

from erp_api.core.config import get_settings
from erp_api.services.feishu_table_mirror_client import (
    FEISHU_MIRROR_BATCH_LIMIT,
    FeishuMirrorRecord,
    FeishuTableMirrorClient,
)
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_SOURCE_RECORD_FIELD,
    AI_INVITATION_TIME_FIELD,
)
from erp_api.services.sample_cooperation_parsing import plain_text


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _key(record: FeishuMirrorRecord) -> tuple[str, object]:
    creator_id = plain_text(record.fields.get(AI_INVITATION_CREATOR_FIELD))
    if not creator_id:
        raise RuntimeError(
            f"Mirror adoption found a blank creator: {record.record_id}."
        )
    return creator_id, record.fields.get(AI_INVITATION_TIME_FIELD)


def _group(records: list[FeishuMirrorRecord]):
    grouped = defaultdict(list)
    for record in records:
        grouped[_key(record)].append(record)
    return grouped


async def main(arguments: argparse.Namespace) -> None:
    settings = get_settings()
    app_secret = settings.feishu_app_secret.get_secret_value()
    source = FeishuTableMirrorClient(
        app_id=settings.feishu_app_id,
        app_secret=app_secret,
        base_token=settings.feishu_ai_invitation_base_token.get_secret_value(),
        table_id=settings.feishu_ai_invitation_table_id,
    )
    target = FeishuTableMirrorClient(
        app_id=settings.feishu_app_id,
        app_secret=app_secret,
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_ai_invitation_mirror_table_id,
        writable_fields=(AI_INVITATION_SOURCE_RECORD_FIELD,),
    )
    source_records = list(
        await source.list_records(
            field_names=(AI_INVITATION_CREATOR_FIELD, AI_INVITATION_TIME_FIELD)
        )
    )
    target_records = list(
        await target.list_records(
            field_names=(
                AI_INVITATION_CREATOR_FIELD,
                AI_INVITATION_TIME_FIELD,
                AI_INVITATION_SOURCE_RECORD_FIELD,
            )
        )
    )
    mapped_source_ids = {
        source_id
        for record in target_records
        if (
            source_id := plain_text(
                record.fields.get(AI_INVITATION_SOURCE_RECORD_FIELD)
            )
        )
    }
    source_groups = _group(
        [
            record
            for record in source_records
            if record.record_id not in mapped_source_ids
        ]
    )
    target_groups = _group(
        [
            record
            for record in target_records
            if not plain_text(record.fields.get(AI_INVITATION_SOURCE_RECORD_FIELD))
        ]
    )
    mismatches = {
        repr(key): (len(source_groups.get(key, [])), len(target_groups.get(key, [])))
        for key in set(source_groups) | set(target_groups)
        if len(source_groups.get(key, [])) != len(target_groups.get(key, []))
    }
    if mismatches:
        raise RuntimeError(
            "Mirror adoption source/target rows do not match: "
            + json.dumps(mismatches, ensure_ascii=True)
        )
    updates = []
    for key in sorted(source_groups, key=repr):
        sources = sorted(source_groups[key], key=lambda record: record.record_id)
        targets = sorted(target_groups[key], key=lambda record: record.record_id)
        updates.extend(
            (
                target_record.record_id,
                {AI_INVITATION_SOURCE_RECORD_FIELD: source_record.record_id},
            )
            for source_record, target_record in zip(sources, targets, strict=True)
        )
    if arguments.apply:
        for offset in range(0, len(updates), FEISHU_MIRROR_BATCH_LIMIT):
            await target.batch_update(
                updates[offset : offset + FEISHU_MIRROR_BATCH_LIMIT]
            )
    print(
        json.dumps(
            {
                "apply": arguments.apply,
                "source_count": len(source_records),
                "target_count": len(target_records),
                "mapped_count": len(mapped_source_ids),
                "backfill_count": len(updates),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main(_arguments()))
