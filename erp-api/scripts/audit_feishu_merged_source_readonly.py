"""Read-only completeness check for the merged cooperation source."""

import asyncio
import json
import sys

from erp_api.core.config import get_settings
from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_creator_export_service import (
    FEISHU_MERGED_SOURCE,
    MERGED_SOURCE_LINES,
    FeishuCreatorExportError,
    _field_text,
    build_feishu_creator_export,
)


async def main() -> None:
    settings = get_settings()
    if not settings.feishu_new_app_id or not settings.feishu_new_app_secret:
        print("MERGED_SOURCE=BLOCKED reason=credentials_unavailable")
        return
    if "--record-id" in sys.argv:
        await inspect_record(settings, sys.argv[sys.argv.index("--record-id") + 1])
        return
    if "--unknown-only" in sys.argv:
        await inspect_unknown_sources(settings)
        return
    try:
        payload = await build_feishu_creator_export(
            settings.feishu_new_app_id,
            settings.feishu_new_app_secret.get_secret_value(),
        )
    except FeishuCreatorExportError as error:
        print(f"MERGED_SOURCE=BLOCKED reason={error}")
        await inspect_unknown_sources(settings)
        return
    counts = {row["productLine"]: row["total"] for row in payload["tables"]}
    print(f"MERGED_SOURCE=READY counts={counts}")


async def inspect_unknown_sources(settings) -> None:
    client = FeishuClient(
        app_id=settings.feishu_new_app_id,
        app_secret=settings.feishu_new_app_secret.get_secret_value(),
        business_type="creator_export",
    )
    await client.tenant_access_token()
    token = ""
    seen = set()
    for _ in range(100):
        params = {
            "view_id": FEISHU_MERGED_SOURCE.view_id,
            "field_names": json.dumps(("数据来源",), ensure_ascii=False),
            "page_size": 500,
        }
        if token:
            params["page_token"] = token
        data = await client.list_records(
            FEISHU_MERGED_SOURCE.app_token,
            FEISHU_MERGED_SOURCE.table_id,
            params=params,
        )
        for item in data.get("items") or []:
            source = _field_text((item.get("fields") or {}).get("数据来源"))
            if source not in MERGED_SOURCE_LINES:
                print(
                    "UNKNOWN_SOURCE "
                    f"record_id={item.get('record_id')} value={source[:80]!r}"
                )
                return
        if not data.get("has_more"):
            print("UNKNOWN_SOURCE not_reproduced")
            return
        token = data.get("page_token") or ""
        if not token or token in seen:
            print("UNKNOWN_SOURCE pagination_invalid")
            return
        seen.add(token)
    print("UNKNOWN_SOURCE pagination_limit")


async def inspect_record(settings, record_id: str) -> None:
    client = FeishuClient(
        app_id=settings.feishu_new_app_id,
        app_secret=settings.feishu_new_app_secret.get_secret_value(),
        business_type="creator_export",
    )
    await client.tenant_access_token()
    data = await client.get_record(
        FEISHU_MERGED_SOURCE.app_token,
        FEISHU_MERGED_SOURCE.table_id,
        record_id,
    )
    fields = (data.get("record") or {}).get("fields") or {}
    print(
        "RECORD_FIELDS "
        f"record_id={record_id} "
        f"has_account={bool(_field_text(fields.get('帐号名称')))} "
        f"has_bd={bool(_field_text(fields.get('BD负责人')))} "
        f"has_date={bool(_field_text(fields.get('同意样品日期')))} "
        f"has_source={bool(_field_text(fields.get('数据来源')))}"
    )


if __name__ == "__main__":
    asyncio.run(main())
