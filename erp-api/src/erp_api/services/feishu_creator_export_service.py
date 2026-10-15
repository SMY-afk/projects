import json
from dataclasses import dataclass
from typing import Any

import httpx

from erp_api.services.feishu_client import FeishuClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import DEFAULT_FEISHU_RETRY_DELAYS

FEISHU_CREATOR_FIELDS = ("帐号名称", "BD负责人", "同意样品日期")
FEISHU_MERGED_FIELDS = (*FEISHU_CREATOR_FIELDS, "数据来源")
MERGED_SOURCE_LINES = {"童车团队": "童车", "遥控玩具团队": "遥控车"}


@dataclass(frozen=True)
class FeishuTable:
    product_line: str
    app_token: str
    table_id: str
    view_id: str


FEISHU_TABLES = (
    FeishuTable(
        "童车", "examplefc071571cfacf2fb2208", "tblexamplef60c4307", "vewHmXeS09"
    ),
    FeishuTable(
        "遥控车", "example14571c6e716163d45e6b", "tblexample1012acf0", "vewHmXeS09"
    ),
)
FEISHU_MERGED_SOURCE = FeishuTable(
    "合并", "example2a74f860658b631683d1", "tblexample6a939c85", "vewRqDi0Gi"
)


def configured_feishu_tables(settings: Any) -> tuple[FeishuTable, FeishuTable]:
    """Resolve the two cooperation tables as one complete configuration set."""
    keys = (
        "feishu_coop_stroller_base_token",
        "feishu_coop_stroller_table_id",
        "feishu_coop_stroller_view_id",
        "feishu_coop_rc_base_token",
        "feishu_coop_rc_table_id",
        "feishu_coop_rc_view_id",
    )
    values = [getattr(settings, key, None) for key in keys]
    if not any(values):
        return FEISHU_TABLES
    if not all(values):
        raise ValueError("Both Feishu cooperation tables require complete IDs.")
    return (
        FeishuTable("童车", values[0], values[1], values[2]),
        FeishuTable("遥控车", values[3], values[4], values[5]),
    )


class FeishuCreatorExportError(RuntimeError):
    pass


async def build_feishu_creator_export(
    app_id: str,
    app_secret: str,
    *,
    http_transport: httpx.AsyncBaseTransport | None = None,
    retry_delays: tuple[float, ...] = DEFAULT_FEISHU_RETRY_DELAYS,
) -> dict[str, Any]:
    feishu = FeishuClient(
        app_id=app_id,
        app_secret=app_secret,
        http_transport=http_transport,
        retry_delays=retry_delays,
        business_type="creator_export",
    )
    try:
        await feishu.tenant_access_token()
    except FeishuSampleError:
        raise FeishuCreatorExportError("Feishu token request failed.") from None
    tables = await _read_merged_table(feishu)
    return {"source": "feishu-bitable-readonly", "tables": tables, "warnings": []}


async def _read_merged_table(feishu: FeishuClient) -> list[dict[str, Any]]:
    table = FEISHU_MERGED_SOURCE
    rows: dict[str, list[dict[str, str]]] = {
        line: [] for line in MERGED_SOURCE_LINES.values()
    }
    expected_total: int | None = None
    page_token = ""
    seen_tokens: set[str] = set()
    seen_record_ids: set[str] = set()
    empty_placeholders = 0
    while True:
        params = {
            "view_id": table.view_id,
            "field_names": json.dumps(FEISHU_MERGED_FIELDS, ensure_ascii=False),
            "page_size": 500,
        }
        if page_token:
            params["page_token"] = page_token
        try:
            data = await feishu.list_records(
                table.app_token, table.table_id, params=params
            )
        except FeishuSampleError:
            raise FeishuCreatorExportError(
                f"Feishu {table.product_line} table request failed."
            ) from None
        total = data.get("total")
        if not isinstance(total, int) or total < 0:
            raise FeishuCreatorExportError(
                f"Feishu {table.product_line} table response has no valid total."
            )
        if expected_total is not None and total != expected_total:
            raise FeishuCreatorExportError(
                f"Feishu {table.product_line} table total changed during pagination."
            )
        expected_total = total if expected_total is None else expected_total
        items = data.get("items")
        if not isinstance(items, list):
            raise FeishuCreatorExportError(
                f"Feishu {table.product_line} table response has no item list."
            )
        for item in items:
            record_id = item.get("record_id") if isinstance(item, dict) else None
            if not isinstance(record_id, str) or not record_id:
                raise FeishuCreatorExportError(
                    f"Feishu {table.product_line} table has no record ID."
                )
            if record_id in seen_record_ids:
                raise FeishuCreatorExportError(
                    f"Feishu {table.product_line} table repeated a record."
                )
            seen_record_ids.add(record_id)
        for item in items:
            fields = item.get("fields") if isinstance(item, dict) else None
            if not isinstance(fields, dict):
                raise FeishuCreatorExportError(
                    "Feishu merged table has invalid record fields."
                )
            if all(not _field_text(fields.get(name)) for name in FEISHU_MERGED_FIELDS):
                empty_placeholders += 1
                continue
            source = _field_text((fields or {}).get(FEISHU_MERGED_FIELDS[-1]))
            line = MERGED_SOURCE_LINES.get(source)
            if line is None:
                raise FeishuCreatorExportError(
                    "Feishu merged table has unknown data source."
                )
            rows[line].append(_creator_row(item))
        if not data.get("has_more"):
            break
        next_token = data.get("page_token")
        if (
            not isinstance(next_token, str)
            or not next_token
            or next_token in seen_tokens
        ):
            raise FeishuCreatorExportError(
                f"Feishu {table.product_line} table pagination is invalid."
            )
        seen_tokens.add(next_token)
        page_token = next_token
    captured = sum(len(items) for items in rows.values()) + empty_placeholders
    if captured != expected_total:
        raise FeishuCreatorExportError(
            f"Feishu {table.product_line} table is incomplete: "
            f"captured={captured}, total={expected_total}."
        )
    return [
        {"productLine": line, "total": len(rows[line]), "rows": rows[line]}
        for line in ("童车", "遥控车")
    ]


def _creator_row(item: Any) -> dict[str, str]:
    fields = item.get("fields", {}) if isinstance(item, dict) else {}
    if not isinstance(fields, dict):
        fields = {}
    return {
        "accountName": _field_text(fields.get(FEISHU_CREATOR_FIELDS[0])),
        "bdOwner": _field_single_text(fields.get(FEISHU_CREATOR_FIELDS[1])),
        "sampleApprovedDate": _field_text(fields.get(FEISHU_CREATOR_FIELDS[2])),
    }


def _field_single_text(value: Any) -> str:
    if isinstance(value, list):
        for item in reversed(value):
            if text := _field_single_text(item):
                return text
        return ""
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if key in value:
                return _field_single_text(value[key])
        return ""
    return _field_text(value)


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_field_text(item) for item in value]
        return "；".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if key in value:
                return _field_text(value[key])
    return ""
