from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_errors import FeishuSampleError

FEISHU_MIRROR_BATCH_LIMIT = 500


@dataclass(frozen=True)
class FeishuMirrorRecord:
    record_id: str
    fields: dict[str, Any]


class FeishuTableMirrorClient(FeishuSampleClient):
    def __init__(self, *, writable_fields: Sequence[str] = (), **kwargs) -> None:
        super().__init__(**kwargs)
        self._writable_fields = frozenset(writable_fields)

    async def list_records(
        self, *, field_names: Sequence[str]
    ) -> tuple[FeishuMirrorRecord, ...]:
        token = await self.tenant_access_token()
        records: list[FeishuMirrorRecord] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        page_token: str | None = None
        expected_total: int | None = None
        while True:
            params: dict[str, object] = {
                "page_size": FEISHU_MIRROR_BATCH_LIMIT,
                "field_names": json.dumps(list(field_names), ensure_ascii=False),
            }
            if page_token:
                params["page_token"] = page_token
            data = await self._request(
                "GET", self._record_path(), token=token, params=params
            )
            total = data.get("total")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise FeishuSampleError("Feishu mirror record total is invalid.")
            if expected_total is not None and total != expected_total:
                raise FeishuSampleError(
                    "Feishu mirror record total changed between pages."
                )
            expected_total = total
            items = data.get("items")
            if items is None and total == 0:
                items = []
            if not isinstance(items, list):
                raise FeishuSampleError("Feishu mirror record list is invalid.")
            for item in items:
                record = self._parse_record(item)
                if record.record_id in seen_ids:
                    raise FeishuSampleError("Feishu mirror record ID is duplicated.")
                seen_ids.add(record.record_id)
                records.append(record)
            if data.get("has_more") is not True:
                break
            next_token = data.get("page_token")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_tokens
            ):
                raise FeishuSampleError("Feishu mirror pagination is incomplete.")
            seen_tokens.add(next_token)
            page_token = next_token
        if len(records) != expected_total:
            raise FeishuSampleError("Feishu mirror record total is incomplete.")
        return tuple(records)

    async def batch_create(self, rows: Sequence[Mapping[str, Any]]) -> int:
        self._validate_rows(rows)
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_create",
            token=token,
            retry_mode="rate_limit",
            json={"records": [{"fields": dict(row)} for row in rows]},
        )
        return self._validate_response_count(data, len(rows), "create")

    async def batch_update(self, rows: Sequence[tuple[str, Mapping[str, Any]]]) -> int:
        if not rows or len(rows) > FEISHU_MIRROR_BATCH_LIMIT:
            raise ValueError("Feishu mirror update batch size is invalid.")
        record_ids = [record_id for record_id, _fields in rows]
        if any(not record_id for record_id in record_ids) or len(
            set(record_ids)
        ) != len(record_ids):
            raise ValueError("Feishu mirror update record IDs are invalid.")
        self._validate_rows([fields for _record_id, fields in rows])
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_update",
            token=token,
            retry_mode="idempotent",
            json={
                "records": [
                    {"record_id": record_id, "fields": dict(fields)}
                    for record_id, fields in rows
                ]
            },
        )
        return self._validate_response_count(data, len(rows), "update")

    async def batch_delete(self, record_ids: Sequence[str]) -> int:
        if not record_ids or len(record_ids) > FEISHU_MIRROR_BATCH_LIMIT:
            raise ValueError("Feishu mirror delete batch size is invalid.")
        if any(not value for value in record_ids) or len(set(record_ids)) != len(
            record_ids
        ):
            raise ValueError("Feishu mirror delete record IDs are invalid.")
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_delete",
            token=token,
            retry_mode="idempotent",
            json={"records": list(record_ids)},
        )
        return self._validate_response_count(data, len(record_ids), "delete")

    def _validate_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows or len(rows) > FEISHU_MIRROR_BATCH_LIMIT:
            raise ValueError("Feishu mirror write batch size is invalid.")
        if any(not row or not set(row) <= self._writable_fields for row in rows):
            raise ValueError("Feishu mirror row contains unsupported fields.")

    @staticmethod
    def _parse_record(item: object) -> FeishuMirrorRecord:
        if not isinstance(item, dict):
            raise FeishuSampleError("Feishu mirror record is invalid.")
        record_id = item.get("record_id")
        fields = item.get("fields")
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(fields, dict)
        ):
            raise FeishuSampleError("Feishu mirror record is invalid.")
        return FeishuMirrorRecord(record_id, dict(fields))

    @staticmethod
    def _validate_response_count(data: dict[str, Any], count: int, action: str) -> int:
        records = data.get("records")
        if not isinstance(records, list) or len(records) != count:
            raise FeishuSampleError(
                f"Feishu mirror batch {action} response is incomplete."
            )
        return len(records)
