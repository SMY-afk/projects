from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.sample_assignment_record_service import (
    ASSIGNMENT_RECORD_SCHEMA,
)

LEGACY_ASSIGNMENT_RECORD_SCHEMA = (
    ("分配编号", 1),
    ("申请编号", 1),
    ("达人昵称", 1),
    ("样品编号", 1),
    ("分配BD", 1),
    ("分配人", 1),
    ("分配时间", 5),
    ("通知状态", 1),
    ("通知时间", 5),
    ("备注", 1),
)
PREVIOUS_ASSIGNMENT_RECORD_SCHEMA = tuple(
    spec for spec in ASSIGNMENT_RECORD_SCHEMA if spec[0] != "分配提醒"
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.table_id.startswith("tbl"):
        raise ValueError("Feishu assignment table ID is invalid.")
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        raise RuntimeError("Feishu sample connection is not configured.")
    client = FeishuAssignmentRecordClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=args.table_id,
    )
    fields = await client.list_field_metadata()
    current = tuple(fields.values())
    supported_schemas = (
        LEGACY_ASSIGNMENT_RECORD_SCHEMA,
        PREVIOUS_ASSIGNMENT_RECORD_SCHEMA,
        ASSIGNMENT_RECORD_SCHEMA,
    )
    positional_schema = next(
        (schema for schema in supported_schemas if len(schema) == len(current)),
        None,
    )
    if positional_schema is None:
        raise RuntimeError("Feishu assignment table schema is unexpected.")
    current_names = {field.field_name for field in current}
    supported_name_sets = (
        {name for name, _ in schema} for schema in supported_schemas
    )
    named_schema = current_names in supported_name_sets
    if not named_schema and any(
        field.field_name not in {f"列{index}", target_name}
        for index, (field, (target_name, _)) in enumerate(
            zip(current, positional_schema, strict=True), start=1
        )
    ):
        raise RuntimeError("Feishu assignment table schema is unexpected.")
    records = await client.list_record_snapshots()
    header = next(
        (
            record
            for record in records
            if record.snapshot.fields.get(current[0].field_name) == "分配编号"
        ),
        None,
    )
    ready = all(
        fields.get(name) is not None and fields[name].field_type == field_type
        for name, field_type in ASSIGNMENT_RECORD_SCHEMA
    )
    print(
        json.dumps(
            {
                "status": "ready" if ready else "change_required",
                "header_placeholder": header is not None,
                "apply": args.apply,
            },
            ensure_ascii=False,
        )
    )
    if not args.apply or ready:
        return
    token = await client.tenant_access_token()
    if header is not None:
        await client._request(
            "PUT",
            client._record_path(header.record_id),
            token=token,
            json={
                "fields": {field.field_name: None for field in current}
            },
        )
    update_schema = (
        positional_schema
        if not named_schema
        else tuple(
            ("达人ID", field.field_type)
            if field.field_name == "达人昵称"
            else (field.field_name, field.field_type)
            for field in current
        )
    )
    for field, (target_name, target_type) in zip(
        current, update_schema, strict=True
    ):
        if field.field_name == target_name and field.field_type == target_type:
            continue
        payload: dict[str, object] = {
            "field_name": target_name,
            "type": target_type,
        }
        if target_type == 5:
            payload["property"] = {"date_formatter": "yyyy-MM-dd HH:mm"}
        await client._request(
            "PUT",
            f"{client._field_path()}/{field.field_id}",
            token=token,
            json=payload,
        )
    updated_names = {name for name, _ in update_schema}
    for field_name, field_type in ASSIGNMENT_RECORD_SCHEMA:
        if field_name in updated_names:
            continue
        await client._request(
            "POST",
            client._field_path(),
            token=token,
            json={"field_name": field_name, "type": field_type},
        )
    verified = await client.list_field_metadata()
    if not all(
        verified.get(name) is not None
        and verified[name].field_type == field_type
        for name, field_type in ASSIGNMENT_RECORD_SCHEMA
    ):
        raise RuntimeError("Feishu assignment table conversion was not verified.")
    print(
        json.dumps(
            {"status": "updated", "verified_fields": len(ASSIGNMENT_RECORD_SCHEMA)}
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
