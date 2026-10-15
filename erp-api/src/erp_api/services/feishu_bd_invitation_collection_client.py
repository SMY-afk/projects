from __future__ import annotations

from collections.abc import Sequence

from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.sample_bd_invitation_protection import (
    BD_INVITATION_CREATOR_FIELD,
    BD_INVITATION_ORIGINAL_SUBMITTER_FIELD,
    BD_INVITATION_OWNER_FIELD,
    BD_INVITATION_REMARK_FIELD,
)


class FeishuBdInvitationCollectionClient(FeishuSampleBatchClient):
    async def batch_update_split_records(
        self,
        records: Sequence[tuple[str, str, str]],
    ) -> tuple[str, ...]:
        self._validate_batch_size(records)
        record_ids: set[str] = set()
        request_records: list[dict[str, object]] = []
        for record_id, creator_id, original_submitter in records:
            if (
                not record_id
                or record_id in record_ids
                or not creator_id.strip()
                or not original_submitter.strip()
            ):
                raise ValueError("Collection split update is invalid or duplicated.")
            record_ids.add(record_id)
            request_records.append(
                {
                    "record_id": record_id,
                    "fields": {
                        BD_INVITATION_CREATOR_FIELD: creator_id,
                        BD_INVITATION_ORIGINAL_SUBMITTER_FIELD: original_submitter,
                    },
                }
            )
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_update",
            token=token,
            retry_mode="idempotent",
            json={"records": request_records},
        )
        return self._response_updated_record_ids(data, record_ids, "split update")

    async def batch_create_invitations(
        self,
        records: Sequence[tuple[str, str, str]],
    ) -> tuple[str, ...]:
        self._validate_batch_size(records)
        request_records = []
        for creator_id, bd_name, original_submitter in records:
            if (
                not creator_id.strip()
                or not bd_name.strip()
                or not original_submitter.strip()
            ):
                raise ValueError("Collection invitation create is invalid.")
            request_records.append(
                {
                    "fields": {
                        BD_INVITATION_CREATOR_FIELD: creator_id,
                        BD_INVITATION_OWNER_FIELD: bd_name,
                        BD_INVITATION_ORIGINAL_SUBMITTER_FIELD: original_submitter,
                    }
                }
            )
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_create",
            token=token,
            retry_mode="rate_limit",
            json={"records": request_records},
        )
        return self._response_record_ids(data, len(records), "invitation create")

    async def batch_update_remarks(
        self,
        records: Sequence[tuple[str, str]],
    ) -> tuple[str, ...]:
        return await self._batch_update_text_field(
            records,
            field_name=BD_INVITATION_REMARK_FIELD,
            operation="remark update",
        )

    async def _batch_update_text_field(
        self,
        records: Sequence[tuple[str, str]],
        *,
        field_name: str,
        operation: str,
    ) -> tuple[str, ...]:
        self._validate_batch_size(records)
        record_ids: set[str] = set()
        request_records: list[dict[str, object]] = []
        for record_id, value in records:
            if not record_id or record_id in record_ids or not value.strip():
                raise ValueError(f"Collection {operation} is invalid or duplicated.")
            record_ids.add(record_id)
            request_records.append(
                {
                    "record_id": record_id,
                    "fields": {field_name: value},
                }
            )
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            f"{self._record_path()}/batch_update",
            token=token,
            retry_mode="idempotent",
            json={"records": request_records},
        )
        return self._response_updated_record_ids(data, record_ids, operation)

    @staticmethod
    def _response_updated_record_ids(
        data: dict[str, object], record_ids: set[str], operation: str
    ) -> tuple[str, ...]:
        response_records = data.get("records")
        if not isinstance(response_records, list) or len(response_records) != len(
            record_ids
        ):
            raise FeishuSampleError(f"Collection {operation} response is incomplete.")
        updated = tuple(
            item.get("record_id") if isinstance(item, dict) else None
            for item in response_records
        )
        if set(updated) != record_ids:
            raise FeishuSampleError(f"Collection {operation} identity is invalid.")
        return tuple(record_id for record_id in updated if isinstance(record_id, str))

    @staticmethod
    def _response_record_ids(
        data: dict[str, object], expected_count: int, operation: str
    ) -> tuple[str, ...]:
        response_records = data.get("records")
        if (
            not isinstance(response_records, list)
            or len(response_records) != expected_count
        ):
            raise FeishuSampleError(f"Collection {operation} response is incomplete.")
        record_ids = tuple(
            item.get("record_id") if isinstance(item, dict) else None
            for item in response_records
        )
        if any(
            not isinstance(record_id, str) or not record_id for record_id in record_ids
        ):
            raise FeishuSampleError(f"Collection {operation} identity is invalid.")
        return tuple(
            record_id for record_id in record_ids if isinstance(record_id, str)
        )
