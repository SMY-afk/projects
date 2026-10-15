from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_assignment_summary_client import (
    FeishuAssignmentSummaryClient,
)
from erp_api.services.sample_assignment_summary_service import (
    GMV_FIELDS,
    ROW_GMV_TOTAL_FIELD,
)

EXPECTED_FIELDS = {
    "最后同步时间": 5,
    "人工锁定": 7,
    "同步来源": 1,
    **{field_name: 2 for field_name in GMV_FIELDS.values()},
    ROW_GMV_TOTAL_FIELD: 2,
}
GMV_VIEW_NAME = "各店铺BD等级GMV（USD）"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    client = FeishuAssignmentSummaryClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_assignment_summary_table_id,
    )
    current = await client.list_field_metadata()
    token = await client.tenant_access_token()
    view_path = (
        f"/open-apis/bitable/v1/apps/"
        f"{settings.feishu_sample_base_token.get_secret_value()}/tables/"
        f"{settings.feishu_assignment_summary_table_id}/views"
    )
    view_data = await client._request(
        "GET", view_path, token=token, params={"page_size": 100}
    )
    views = view_data.get("items")
    if not isinstance(views, list):
        raise TypeError("Assignment summary view list is invalid.")
    view_exists = any(
        isinstance(view, dict) and view.get("view_name") == GMV_VIEW_NAME
        for view in views
    )
    changes: list[str] = []
    if "最后同步时间" not in current and "最后读取时间" in current:
        changes.append("rename:最后读取时间->最后同步时间")
    for name in ("人工锁定", "同步来源"):
        if name not in current:
            changes.append(f"create:{name}")
    for name in (*GMV_FIELDS.values(), ROW_GMV_TOTAL_FIELD):
        if name not in current:
            changes.append(f"create:{name}")
    if not view_exists:
        changes.append(f"create-view:{GMV_VIEW_NAME}")
    print(json.dumps({"apply": args.apply, "changes": changes}, ensure_ascii=False))
    if not args.apply:
        return

    if "最后同步时间" not in current and "最后读取时间" in current:
        field = current["最后读取时间"]
        await client._request(
            "PUT",
            f"{client._field_path()}/{field.field_id}",
            token=token,
            json={
                "field_name": "最后同步时间",
                "type": 5,
                "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
            },
        )
    for name, field_type in (("人工锁定", 7), ("同步来源", 1)):
        if name in current:
            continue
        await client._request(
            "POST",
            client._field_path(),
            token=token,
            json={"field_name": name, "type": field_type},
        )
    for name in (*GMV_FIELDS.values(), ROW_GMV_TOTAL_FIELD):
        if name in current:
            continue
        await client._request(
            "POST",
            client._field_path(),
            token=token,
            json={
                "field_name": name,
                "type": 2,
                "property": {"formatter": "0.00"},
            },
        )
    if not view_exists:
        await client._request(
            "POST",
            view_path,
            token=token,
            json={"view_name": GMV_VIEW_NAME, "view_type": "grid"},
        )

    verified = await client.list_field_metadata()
    invalid = {
        name: None if verified.get(name) is None else verified[name].field_type
        for name, field_type in EXPECTED_FIELDS.items()
        if verified.get(name) is None or verified[name].field_type != field_type
    }
    if invalid:
        raise RuntimeError(f"Assignment summary fields were not verified: {invalid}")
    verified_views = await client._request(
        "GET", view_path, token=token, params={"page_size": 100}
    )
    if not any(
        isinstance(view, dict) and view.get("view_name") == GMV_VIEW_NAME
        for view in verified_views.get("items", [])
    ):
        raise RuntimeError("Assignment summary GMV view was not verified.")
    print(
        json.dumps(
            {
                "status": "updated",
                "verified": EXPECTED_FIELDS,
                "view": GMV_VIEW_NAME,
                "field_count": len(verified),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
