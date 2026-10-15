from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from erp_api.services.feishu_sample_batch_client import (
    FEISHU_BATCH_RECORD_LIMIT,
    FeishuSampleBatchClient,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError


class FeishuAssignmentRecordClient(FeishuSampleBatchClient):
    """Write assignment audit rows without using sample-table field guards."""

    async def create_assignment_record(self, fields: dict[str, Any]) -> str:
        if not fields or not isinstance(fields.get("分配编号"), str):
            raise ValueError("Feishu assignment record identity is required.")
        token = await self.tenant_access_token()
        data = await self._request(
            "POST", self._record_path(), token=token, json={"fields": fields}
        )
        record = data.get("record")
        record_id = record.get("record_id") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or not record_id:
            raise FeishuSampleError(
                "Feishu assignment create response is missing record_id."
            )
        return record_id

    async def batch_create_assignment_records(
        self, records: Sequence[dict[str, Any]]
    ) -> dict[str, str]:
        if not 1 <= len(records) <= FEISHU_BATCH_RECORD_LIMIT:
            raise ValueError("Feishu assignment create batch size is invalid.")
        numbers = [fields.get("分配编号") for fields in records]
        if any(not isinstance(number, str) or not number for number in numbers):
            raise ValueError("Feishu assignment record identity is required.")
        if len(set(numbers)) != len(numbers):
            raise ValueError("Feishu assignment record identity is duplicated.")
        data = await self._feishu.batch_records(
            self._base_token,
            self._table_id,
            "batch_create",
            [{"fields": fields} for fields in records],
            retry_mode="rate_limit",
        )
        response = data.get("records")
        if not isinstance(response, list) or len(response) != len(records):
            raise FeishuSampleError(
                "Feishu assignment batch create response is incomplete."
            )
        created: dict[str, str] = {}
        record_ids: set[str] = set()
        for item in response:
            fields = item.get("fields") if isinstance(item, dict) else None
            number = fields.get("分配编号") if isinstance(fields, dict) else None
            record_id = item.get("record_id") if isinstance(item, dict) else None
            if (
                number not in numbers
                or number in created
                or not isinstance(record_id, str)
                or not record_id
                or record_id in record_ids
            ):
                raise FeishuSampleError(
                    "Feishu assignment batch create identity is invalid."
                )
            created[number] = record_id
            record_ids.add(record_id)
        return created

    async def batch_update_assignment_records(
        self, records: Sequence[tuple[str, dict[str, Any]]]
    ) -> tuple[str, ...]:
        if not 1 <= len(records) <= FEISHU_BATCH_RECORD_LIMIT:
            raise ValueError("Feishu assignment update batch size is invalid.")
        record_ids = [record_id for record_id, _fields in records]
        if any(not record_id or not fields for record_id, fields in records) or len(
            set(record_ids)
        ) != len(record_ids):
            raise ValueError("Feishu assignment update records are invalid.")
        data = await self._feishu.batch_records(
            self._base_token,
            self._table_id,
            "batch_update",
            [
                {"record_id": record_id, "fields": fields}
                for record_id, fields in records
            ],
            retry_mode="idempotent",
        )
        response = data.get("records")
        if not isinstance(response, list) or len(response) != len(records):
            raise FeishuSampleError(
                "Feishu assignment batch update response is incomplete."
            )
        updated = tuple(
            item.get("record_id") if isinstance(item, dict) else None
            for item in response
        )
        if set(updated) != set(record_ids):
            raise FeishuSampleError(
                "Feishu assignment batch update identity is invalid."
            )
        return tuple(record_id for record_id in updated if isinstance(record_id, str))

    async def update_assignment_record(
        self, record_id: str, fields: dict[str, Any]
    ) -> None:
        if not record_id or not fields:
            raise ValueError("Feishu assignment update is invalid.")
        token = await self.tenant_access_token()
        await self._request(
            "PUT",
            self._record_path(record_id),
            token=token,
            json={"fields": fields},
        )

    async def delete_assignment_record(self, record_id: str) -> None:
        if not record_id:
            raise ValueError("Feishu assignment record identity is required.")
        token = await self.tenant_access_token()
        await self._request("DELETE", self._record_path(record_id), token=token)
