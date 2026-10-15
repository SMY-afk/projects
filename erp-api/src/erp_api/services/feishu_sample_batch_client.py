from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from erp_api.services.feishu_sample_client import FeishuSampleClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS, SYSTEM_FIELDS
from erp_api.services.feishu_sample_record_index import SYNC_KEY_FIELD
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    parse_feishu_record_snapshot,
)

FEISHU_BATCH_RECORD_LIMIT = 500


class FeishuSampleBatchClient(FeishuSampleClient):
    async def batch_get_record_snapshots(
        self, record_ids: Sequence[str]
    ) -> tuple[FeishuListedRecord, ...]:
        normalized = tuple(record_id.strip() for record_id in record_ids)
        if (
            not 1 <= len(normalized) <= 100
            or any(not record_id for record_id in normalized)
            or len(set(normalized)) != len(normalized)
        ):
            raise ValueError("Feishu batch-get record IDs are invalid.")
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_get",
            token=await self.tenant_access_token(),
            retry_mode="idempotent",
            json={"record_ids": list(normalized)},
        )
        items = data.get("records")
        if not isinstance(items, list) or len(items) != len(normalized):
            raise FeishuSampleError("Feishu batch-get response is incomplete.")
        records = tuple(
            FeishuListedRecord(
                item.get("record_id"), parse_feishu_record_snapshot(item)
            )
            for item in items
            if isinstance(item, dict) and isinstance(item.get("record_id"), str)
        )
        if len(records) != len(normalized) or {
            record.record_id for record in records
        } != set(normalized):
            raise FeishuSampleError("Feishu batch-get identity is invalid.")
        return records

    async def list_record_snapshots(
        self,
        *,
        view_id: str | None = None,
        field_names: Sequence[str] | None = None,
        modified_since_date: str | None = None,
    ) -> tuple[FeishuListedRecord, ...]:
        records: list[FeishuListedRecord] = []
        seen_record_ids: set[str] = set()
        seen_page_tokens: set[str] = set()
        page_token: str | None = None
        expected_total: int | None = None
        while True:
            params: dict[str, object] = {
                "page_size": FEISHU_BATCH_RECORD_LIMIT,
                "automatic_fields": True,
            }
            if view_id:
                params["view_id"] = view_id
            if field_names:
                params["field_names"] = json.dumps(
                    list(field_names), ensure_ascii=False
                )
            if modified_since_date:
                params["filter"] = (
                    f'CurrentValue.[最后修改时间] >= TODATE("{modified_since_date}")'
                )
            if page_token:
                params["page_token"] = page_token
            data = await self._feishu.list_records(
                self._base_token, self._table_id, params=params
            )
            total = data.get("total")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise FeishuSampleError("Feishu record total is invalid.")
            if expected_total is not None and total != expected_total:
                raise FeishuSampleError("Feishu record total changed between pages.")
            expected_total = total
            items = data.get("items")
            if items is None and total == 0:
                items = []
            if not isinstance(items, list):
                raise FeishuSampleError("Feishu record list is invalid.")
            for item in items:
                record_id = item.get("record_id") if isinstance(item, dict) else None
                if (
                    not isinstance(record_id, str)
                    or not record_id
                    or record_id in seen_record_ids
                ):
                    raise FeishuSampleError("Feishu record identity is invalid.")
                seen_record_ids.add(record_id)
                records.append(
                    FeishuListedRecord(record_id, parse_feishu_record_snapshot(item))
                )
            has_more = data.get("has_more")
            if not isinstance(has_more, bool):
                raise FeishuSampleError("Feishu record pagination flag is invalid.")
            if not has_more:
                break
            next_token = data.get("page_token")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_page_tokens
            ):
                raise FeishuSampleError("Feishu record pagination is incomplete.")
            seen_page_tokens.add(next_token)
            page_token = next_token
        if len(records) != expected_total:
            raise FeishuSampleError("Feishu record total is incomplete.")
        return tuple(records)

    async def batch_create_records(
        self,
        records: Sequence[dict[str, Any]],
    ) -> dict[str, str]:
        self._validate_batch_size(records)
        sync_keys: set[str] = set()
        request_records: list[dict[str, object]] = []
        for fields in records:
            self._validate_system_fields(fields)
            sync_key = fields.get(SYNC_KEY_FIELD)
            if not isinstance(sync_key, str) or not sync_key:
                raise ValueError("Feishu create record requires a sync key.")
            if sync_key in sync_keys:
                raise ValueError(f"Feishu create sync key is duplicated: {sync_key}.")
            sync_keys.add(sync_key)
            request_records.append({"fields": fields})
        data = await self._feishu.batch_records(
            self._base_token,
            self._table_id,
            "batch_create",
            request_records,
            retry_mode="rate_limit",
        )
        response_records = data.get("records")
        if not isinstance(response_records, list) or len(response_records) != len(
            records
        ):
            raise FeishuSampleError("Feishu batch create response is incomplete.")
        created: dict[str, str] = {}
        for item in response_records:
            sync_key, record_id = self._response_record_identity(item)
            if sync_key not in sync_keys or sync_key in created:
                raise FeishuSampleError("Feishu batch create identity is invalid.")
            created[sync_key] = record_id
        return created

    async def batch_update_records(
        self,
        records: Sequence[tuple[str, dict[str, Any]]],
    ) -> tuple[str, ...]:
        for _record_id, fields in records:
            self._validate_system_fields(fields)
        return await self._batch_update_records(records)

    async def batch_update_business_fields(
        self,
        records: Sequence[tuple[str, dict[str, Any]]],
    ) -> tuple[str, ...]:
        if any(
            not fields or not set(fields) <= BUSINESS_FIELDS for _, fields in records
        ):
            raise ValueError("Only non-empty Feishu business fields are allowed.")
        return await self._batch_update_records(records)

    async def _batch_update_records(
        self,
        records: Sequence[tuple[str, dict[str, Any]]],
    ) -> tuple[str, ...]:
        self._validate_batch_size(records)
        record_ids: set[str] = set()
        request_records: list[dict[str, object]] = []
        for record_id, fields in records:
            if not record_id or record_id in record_ids:
                raise ValueError("Feishu update record_id is invalid or duplicated.")
            record_ids.add(record_id)
            request_records.append({"record_id": record_id, "fields": fields})
        data = await self._feishu.batch_records(
            self._base_token,
            self._table_id,
            "batch_update",
            request_records,
            retry_mode="idempotent",
        )
        response_records = data.get("records")
        if not isinstance(response_records, list) or len(response_records) != len(
            records
        ):
            raise FeishuSampleError("Feishu batch update response is incomplete.")
        updated: list[str] = []
        for item in response_records:
            if not isinstance(item, dict) or not isinstance(item.get("record_id"), str):
                raise FeishuSampleError("Feishu batch update record is invalid.")
            record_id = item["record_id"]
            if record_id not in record_ids or record_id in updated:
                raise FeishuSampleError("Feishu batch update identity is invalid.")
            updated.append(record_id)
        return tuple(updated)

    async def batch_delete_records(
        self,
        record_ids: Sequence[str],
    ) -> tuple[str, ...]:
        self._validate_batch_size(record_ids)
        normalized = tuple(record_id.strip() for record_id in record_ids)
        if any(not record_id for record_id in normalized) or len(
            set(normalized)
        ) != len(normalized):
            raise ValueError("Feishu delete record IDs are invalid or duplicated.")
        data = await self._feishu.batch_records(
            self._base_token,
            self._table_id,
            "batch_delete",
            list(normalized),
            retry_mode="idempotent",
        )
        response_records = data.get("records")
        if not isinstance(response_records, list) or len(response_records) != len(
            normalized
        ):
            raise FeishuSampleError("Feishu batch delete response is incomplete.")
        deleted = tuple(
            item.get("record_id") if isinstance(item, dict) else None
            for item in response_records
        )
        if set(deleted) != set(normalized):
            raise FeishuSampleError("Feishu batch delete identity is invalid.")
        return tuple(record_id for record_id in deleted if isinstance(record_id, str))

    @staticmethod
    def _validate_batch_size(records: Sequence[object]) -> None:
        if not 1 <= len(records) <= FEISHU_BATCH_RECORD_LIMIT:
            raise ValueError("Feishu record batch size must be between 1 and 500.")

    @staticmethod
    def _validate_system_fields(fields: dict[str, Any]) -> None:
        if not fields or not set(fields) <= SYSTEM_FIELDS:
            raise ValueError("Only non-empty Feishu system fields are allowed.")

    @staticmethod
    def _response_record_identity(item: object) -> tuple[str, str]:
        if not isinstance(item, dict):
            raise FeishuSampleError("Feishu batch create record is invalid.")
        record_id = item.get("record_id")
        fields = item.get("fields")
        sync_key = fields.get(SYNC_KEY_FIELD) if isinstance(fields, dict) else None
        if (
            not isinstance(record_id, str)
            or not record_id
            or not isinstance(sync_key, str)
            or not sync_key
        ):
            raise FeishuSampleError("Feishu batch create record is invalid.")
        return sync_key, record_id
