"""Authenticated read-only source and target access for creator reconciliation."""

from __future__ import annotations

import asyncio

import httpx
from dateutil.relativedelta import relativedelta

from erp_api.core.config import get_settings
from erp_api.services.feishu_client import FeishuClient
from scripts.daily_valid_creator_accounts import read_accounts as read_creator_tables
from scripts.daily_valid_creator_core import SHOP_ORDER
from scripts.daily_valid_creator_dates import ShopCutoffs

BASE = "exampleb6b20e30bcdc75e12b5f"
TABLE = "tblexamplef1d0cfa5"
EXPORT_URL = "http://127.0.0.1:8080/api/internal/affiliate-center/"
FIELD_TYPES = {
    "账号名称": 1,
    "BD负责人": 1,
    "匹配店铺": 1,
    "最近有效日期": 5,
    "同意样品日期": 5,
    "业绩": 2,
    "视频数": 2,
    "直播数": 2,
    "保留原因": 1,
    "数据质量备注": 1,
    "最新更新时间": 5,
}


async def _read_stable_accounts(client) -> dict:
    for attempt in range(2):
        try:
            return await read_creator_tables(client)
        except ValueError as error:
            if (attempt == 1 or str(error) !=
                    "Cooperation account total changed during pagination"):
                raise
    raise RuntimeError("Complete cooperation snapshot is unavailable")


async def fetch_sources(
    cutoffs: ShopCutoffs, *, export_url: str = EXPORT_URL
) -> tuple[dict, dict, dict]:
    configured = get_settings().affiliate_export_service_token
    token = configured.get_secret_value() if configured else None
    if not token:
        raise RuntimeError("ERP service export access is unavailable")
    semaphore = asyncio.Semaphore(3)

    timeout = httpx.Timeout(connect=10, read=480, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:

        async def fetch_shop(name: str, resource: str) -> dict:
            end = (
                max(cutoffs[name]["creators"], cutoffs[name]["liveAccounts"])
                if resource == "creators"
                else cutoffs[name][resource]
            )
            start = end - relativedelta(months=2)
            async with semaphore:
                response = await client.get(
                    export_url + "local-export",
                    headers={"x-erp-service-token": token},
                    params={"from": str(start), "to": str(end), "shop": name},
                )
            if response.status_code != 200:
                raise RuntimeError(
                    f"{name}.{resource} live ERP export failed: HTTP {response.status_code}"
                )
            payload = response.json()
            if (
                payload.get("source") != "local-erp-affiliate-center"
                or payload.get("window") != {"from": str(start), "to": str(end)}
                or len(payload.get("shops") or []) != 1
                or payload["shops"][0].get("shopName") != name
            ):
                raise ValueError(f"{name}.{resource} ERP export identity mismatch")
            return payload["shops"][0]

        # Keep prerequisite pagination in this independent worker. Deploying its
        # reader must not require an API restart or interrupt sample ingestion.
        accounts = await _read_stable_accounts(feishu_client())
        high = await asyncio.gather(*(fetch_shop(name, "creators") for name in SHOP_ORDER))

        async def video_source(name, existing):
            end = cutoffs[name]["videos"]
            expected = {"from": str(end - relativedelta(months=2)), "to": str(end)}
            if existing.get("sourceWindows", {}).get("videos") == expected:
                return existing
            return await fetch_shop(name, "videos")

        low = await asyncio.gather(*(video_source(name, row)
                                  for name, row in zip(SHOP_ORDER, high, strict=True)))
    return (
        {"source": "feishu-bitable-readonly", "accounts": accounts},
        {"source": "local-erp-affiliate-center", "shops": high},
        {"source": "local-erp-affiliate-center", "shops": low},
    )


def feishu_client() -> FeishuClient:
    settings = get_settings()
    if not settings.feishu_new_app_id or not settings.feishu_new_app_secret:
        raise RuntimeError("Dedicated Feishu app credentials are unavailable")
    return FeishuClient(
        app_id=settings.feishu_new_app_id,
        app_secret=settings.feishu_new_app_secret.get_secret_value(),
        business_type="daily_valid_creator_sync",
    )


async def verify_target_identity(client: FeishuClient) -> None:
    token = await client.tenant_access_token()
    header = {"Authorization": "Bearer " + token}
    app = await client.request_json(
        "GET",
        f"/open-apis/bitable/v1/apps/{BASE}",
        retry_mode="idempotent",
        headers=header,
    )
    if app.get("data", {}).get("app", {}).get("name") != "样品--副本":
        raise ValueError("Target Base title mismatch")
    tables = await client.request_json(
        "GET",
        f"/open-apis/bitable/v1/apps/{BASE}/tables",
        retry_mode="idempotent",
        headers=header,
        params={"page_size": 100},
    )
    names = {
        item.get("table_id"): item.get("name")
        for item in tables.get("data", {}).get("items", [])
    }
    if names.get(TABLE) != "（每日更新）有效达人":
        raise ValueError("Target table title mismatch")
    fields = await client.request_json(
        "GET",
        f"/open-apis/bitable/v1/apps/{BASE}/tables/{TABLE}/fields",
        retry_mode="idempotent",
        headers=header,
        params={"page_size": 100},
    )
    actual = {
        item.get("field_name"): item.get("type")
        for item in fields.get("data", {}).get("items", [])
    }
    # The authorized cutover removes only this column after both readers deploy.
    if actual not in (FIELD_TYPES, {"产品线": 1, **FIELD_TYPES}):
        raise ValueError("Target field schema mismatch")


async def target_rows(client: FeishuClient) -> list[dict]:
    rows: list[dict] = []
    page_token = ""
    seen = set()
    total = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        data = await client.list_records(BASE, TABLE, params=params)
        if total is None:
            total = data.get("total")
        if data.get("total") != total or not isinstance(data.get("items"), list):
            raise ValueError("Target pagination total changed")
        rows.extend(data["items"])
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token or page_token in seen:
            raise ValueError("Target pagination token is invalid")
        seen.add(page_token)
    record_ids = [row.get("record_id") for row in rows]
    if (
        len(rows) != total
        or any(
            not isinstance(record_id, str) or not record_id for record_id in record_ids
        )
        or len(set(record_ids)) != len(rows)
    ):
        raise ValueError("Target pagination is incomplete or repeated")
    return rows
