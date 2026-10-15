from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient

BD_NAME_FIELD = "BD姓名"
BD_PERSON_FIELD = "飞书人员"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.table_id.startswith("tbl"):
        raise ValueError("Feishu roster table ID is invalid.")
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        raise RuntimeError("Feishu sample connection is not configured.")
    client = FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=args.table_id,
    )
    fields = await client.list_field_metadata()
    person = fields.get(BD_PERSON_FIELD)
    if person is None:
        raise RuntimeError("Feishu BD person field was not found.")
    records = await client.list_record_snapshots()
    header = next(
        (
            record
            for record in records
            if record.snapshot.fields.get(BD_NAME_FIELD) == BD_NAME_FIELD
        ),
        None,
    )
    print(
        json.dumps(
            {
                "status": "ready" if person.field_type == 11 else "change_required",
                "current_type": person.field_type,
                "header_placeholder": bool(
                    header
                    and header.snapshot.fields.get(BD_PERSON_FIELD) == BD_PERSON_FIELD
                ),
                "apply": args.apply,
            }
        )
    )
    if not args.apply or person.field_type == 11:
        return
    token = await client.tenant_access_token()
    if header and header.snapshot.fields.get(BD_PERSON_FIELD) is not None:
        await client._request(
            "PUT",
            client._record_path(header.record_id),
            token=token,
            json={"fields": {BD_PERSON_FIELD: None}},
        )
    await client._request(
        "PUT",
        f"{client._field_path()}/{person.field_id}",
        token=token,
        json={
            "field_name": BD_PERSON_FIELD,
            "type": 11,
            "property": {"multiple": False},
        },
    )
    verified = (await client.list_field_metadata())[BD_PERSON_FIELD]
    if verified.field_type != 11:
        raise RuntimeError("Feishu BD person field conversion was not verified.")
    print(json.dumps({"status": "updated", "verified_type": verified.field_type}))


if __name__ == "__main__":
    asyncio.run(main())
