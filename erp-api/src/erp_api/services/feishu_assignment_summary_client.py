from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from erp_api.services.feishu_sample_batch_client import (
    FEISHU_BATCH_RECORD_LIMIT,
    FeishuSampleBatchClient,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError


class FeishuAssignmentSummaryClient(FeishuSampleBatchClient):
    async def batch_update_summary_records(
        self,
        records: Sequence[tuple[str, dict[str, Any]]],
    ) -> None:
        if not 1 <= len(records) <= FEISHU_BATCH_RECORD_LIMIT:
            raise ValueError("Feishu summary update batch size is invalid.")
        record_ids = [record_id for record_id, _fields in records]
        if any(not record_id for record_id in record_ids) or len(
            set(record_ids)
        ) != len(record_ids):
            raise ValueError("Feishu summary record IDs are invalid or duplicated.")
        if any(not fields for _record_id, fields in records):
            raise ValueError("Feishu summary update fields cannot be empty.")
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_update",
            token=token,
            retry_mode="idempotent",
            json={
                "records": [
                    {"record_id": record_id, "fields": fields}
                    for record_id, fields in records
                ]
            },
        )
        self._validate_response(data, len(records))

    async def batch_create_summary_records(
        self,
        records: Sequence[dict[str, Any]],
    ) -> None:
        if not 1 <= len(records) <= FEISHU_BATCH_RECORD_LIMIT:
            raise ValueError("Feishu summary create batch size is invalid.")
        if any(not fields for fields in records):
            raise ValueError("Feishu summary create fields cannot be empty.")
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_create",
            token=token,
            retry_mode="rate_limit",
            json={"records": [{"fields": fields} for fields in records]},
        )
        self._validate_response(data, len(records))

    @staticmethod
    def _validate_response(data: dict[str, Any], expected: int) -> None:
        records = data.get("records")
        if not isinstance(records, list) or len(records) != expected:
            raise FeishuSampleError("Feishu summary batch response is incomplete.")
