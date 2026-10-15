from __future__ import annotations

import asyncio
import json

from erp_api.core.config import get_settings
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError

TARGET_NAMES = frozenset({"李鸿程", "吴洵涛", "刘诚"})


async def main() -> None:
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
        table_id=settings.feishu_sample_table_id or "not-configured",
    )
    token = await client.tenant_access_token()
    page_token = None
    matched = []
    with client.capture_evidence() as trace:
        try:
            while True:
                params = {
                    "department_id": "0",
                    "department_id_type": "open_department_id",
                    "user_id_type": "open_id",
                    "page_size": 50,
                }
                if page_token:
                    params["page_token"] = page_token
                data = await client._request(
                    "GET",
                    "/open-apis/contact/v3/users/find_by_department",
                    token=token,
                    params=params,
                )
                for item in data.get("items", []):
                    if isinstance(item, dict) and item.get("name") in TARGET_NAMES:
                        matched.append(item.get("name"))
                if data.get("has_more") is not True:
                    break
                page_token = data.get("page_token")
                if not isinstance(page_token, str) or not page_token:
                    raise RuntimeError("Feishu contact pagination is invalid.")
        except FeishuSampleError:
            evidence = trace.responses[-1] if trace.responses else None
            print(
                json.dumps(
                    {
                        "status": "rejected",
                        "error_code": evidence.error_code if evidence else None,
                        "http_status": evidence.http_status if evidence else None,
                    }
                )
            )
            return
    print(json.dumps({"matched_names": sorted(matched), "matched_count": len(matched)}))


if __name__ == "__main__":
    asyncio.run(main())
