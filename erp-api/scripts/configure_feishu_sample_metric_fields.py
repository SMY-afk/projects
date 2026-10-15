from __future__ import annotations

import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_metric_schema import (
    SAMPLE_METRIC_FIELD_SPECS,
    configure_sample_metric_fields,
)


async def main() -> None:
    settings = get_settings()
    required = (
        settings.feishu_app_id,
        settings.feishu_app_secret,
        settings.feishu_sample_base_token,
        settings.feishu_sample_table_id,
    )
    if not all(required):
        raise RuntimeError("Feishu sample table configuration is incomplete.")
    client = FeishuSampleClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_sample_table_id,
    )
    result = await configure_sample_metric_fields(client)
    actual = await client.list_field_metadata()
    for spec in SAMPLE_METRIC_FIELD_SPECS:
        field = actual.get(spec.field_name)
        if (
            field is None
            or field.field_type != spec.field_type
            or field.ui_type != spec.ui_type
            or field.field_property != spec.field_property
        ):
            raise RuntimeError(
                f"Feishu metric field verification failed: {spec.field_name}."
            )
    print(
        json.dumps(
            {
                "status": "succeeded",
                "created_fields": result.created_fields,
                "updated_fields": result.updated_fields,
                "verified_field_count": len(SAMPLE_METRIC_FIELD_SPECS),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
