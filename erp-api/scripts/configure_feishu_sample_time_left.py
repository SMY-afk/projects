from __future__ import annotations

import argparse
import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_time_left_schema import (
    SAMPLE_TIME_LEFT_FIELD_NAME,
    SAMPLE_TIME_LEFT_FIELD_TYPE,
    ensure_sample_time_left_field,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def main(*, apply: bool) -> None:
    settings = get_settings()
    required = (
        settings.feishu_app_id,
        settings.feishu_app_secret,
        settings.feishu_sample_base_token,
    )
    if not all(required):
        raise RuntimeError("Feishu sample table configuration is incomplete.")
    base_token = settings.feishu_sample_base_token.get_secret_value()
    feishu = FeishuClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        business_type="sample_management",
    )
    token = await feishu.tenant_access_token()
    app = await feishu.request_json(
        "GET",
        f"/open-apis/bitable/v1/apps/{base_token}",
        retry_mode="idempotent",
        headers={"Authorization": f"Bearer {token}"},
    )
    if app.get("data", {}).get("app", {}).get("name") != "样品--副本":
        raise RuntimeError("Feishu sample Base title mismatch.")
    table_ids = set(settings.feishu_sample_shop_table_ids.values())
    if settings.feishu_sample_table_id:
        table_ids.add(settings.feishu_sample_table_id)
    if len(table_ids) != 5:
        raise RuntimeError("Exactly five Feishu sample tables must be configured.")

    clients = [
        FeishuSampleClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=base_token,
            table_id=table_id,
        )
        for table_id in sorted(table_ids)
    ]
    actions = [
        await ensure_sample_time_left_field(client, apply=apply) for client in clients
    ]
    verified = 0
    if apply:
        for client in clients:
            fields = await client.list_field_metadata()
            field = fields.get(SAMPLE_TIME_LEFT_FIELD_NAME)
            if field is None or field.field_type != SAMPLE_TIME_LEFT_FIELD_TYPE:
                raise RuntimeError("Feishu sample time-left field verification failed.")
            verified += 1
    print(
        json.dumps(
            {
                "apply": apply,
                "field": SAMPLE_TIME_LEFT_FIELD_NAME,
                "table_count": len(clients),
                "actions": actions,
                "verified": verified,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main(apply=_arguments().apply))
