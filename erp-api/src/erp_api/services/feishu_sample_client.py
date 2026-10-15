from __future__ import annotations

import time
from collections.abc import Callable, Collection
from contextlib import AbstractContextManager
from typing import Any

import httpx

from erp_api.services.feishu_client import TOKEN_REFRESH_SKEW_SECONDS, FeishuClient
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_fields import (
    BUSINESS_FIELDS,
    REQUIRED_SAMPLE_FIELDS,
    SYSTEM_FIELDS,
    FeishuFieldMetadata,
    parse_feishu_field_metadata,
)
from erp_api.services.feishu_sample_record_index import (
    build_record_sync_key_map,
)
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuRecordSnapshot,
    parse_feishu_record_snapshot,
)
from erp_api.services.feishu_sample_transport import (
    DEFAULT_FEISHU_RETRY_DELAYS,
    FeishuRequestTrace,
    RetryMode,
)


class FeishuSampleClient:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_token: str,
        table_id: str,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        token_refresh_skew_seconds: float = TOKEN_REFRESH_SKEW_SECONDS,
        retry_delays: tuple[float, ...] = DEFAULT_FEISHU_RETRY_DELAYS,
    ) -> None:
        self._base_token = base_token
        self._table_id = table_id
        self._feishu = FeishuClient(
            app_id=app_id,
            app_secret=app_secret,
            client=client,
            clock=clock,
            token_refresh_skew_seconds=token_refresh_skew_seconds,
            retry_delays=retry_delays,
            business_type={
                "FeishuAssignmentSummaryClient": "assignment_summary",
                "FeishuAssignmentRecordClient": "assignment_record",
                "FeishuBdInvitationCollectionClient": "bd_invitation",
                "FeishuCreatorLookupClient": "creator_lookup",
                "FeishuTableMirrorClient": "table_mirror",
                "FeishuSheetAiInvitationClient": "ai_invitation",
            }.get(type(self).__name__, "sample_management"),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        retry_mode: RetryMode | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        effective_retry_mode = retry_mode or (
            "idempotent" if method in {"GET", "PUT", "DELETE"} else "rate_limit"
        )
        payload = await self._feishu.request_json(
            method,
            path,
            headers=headers,
            retry_mode=effective_retry_mode,
            **kwargs,
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def capture_evidence(self) -> AbstractContextManager[FeishuRequestTrace]:
        return self._feishu.capture_evidence()

    async def tenant_access_token(self) -> str:
        return await self._feishu.tenant_access_token()

    def _field_path(self) -> str:
        return (
            f"/open-apis/bitable/v1/apps/{self._base_token}/tables/"
            f"{self._table_id}/fields"
        )

    async def list_field_metadata(self) -> dict[str, FeishuFieldMetadata]:
        token = await self.tenant_access_token()
        fields: dict[str, FeishuFieldMetadata] = {}
        page_token: str | None = None
        seen_tokens: set[str] = set()
        expected_total: int | None = None
        while True:
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            data = await self._request(
                "GET", self._field_path(), token=token, params=params
            )
            total = data.get("total")
            if isinstance(total, int) and not isinstance(total, bool):
                expected_total = total
            items = data.get("items")
            if not isinstance(items, list):
                raise FeishuSampleError("Feishu field metadata list is invalid.")
            for item in items:
                field = parse_feishu_field_metadata(item)
                if field.field_name in fields:
                    raise FeishuSampleError(
                        f"Feishu field name is duplicated: {field.field_name}."
                    )
                fields[field.field_name] = field
            if data.get("has_more") is not True:
                break
            next_token = data.get("page_token")
            if (
                not isinstance(next_token, str)
                or not next_token
                or next_token in seen_tokens
            ):
                raise FeishuSampleError("Feishu field pagination is incomplete.")
            seen_tokens.add(next_token)
            page_token = next_token
        if expected_total is not None and len(fields) != expected_total:
            raise FeishuSampleError("Feishu field metadata total is incomplete.")
        return fields

    async def validate_required_fields(
        self,
        required_fields: Collection[str] = REQUIRED_SAMPLE_FIELDS,
    ) -> dict[str, FeishuFieldMetadata]:
        fields = await self.list_field_metadata()
        missing = sorted(set(required_fields) - set(fields))
        if missing:
            raise FeishuSampleError(
                "Feishu sample table is missing required fields: " + ", ".join(missing)
            )
        return fields

    async def create_field_definition(
        self,
        *,
        field_name: str,
        field_type: int,
        ui_type: str,
        field_property: dict[str, object],
    ) -> FeishuFieldMetadata:
        token = await self.tenant_access_token()
        data = await self._request(
            "POST",
            self._field_path(),
            token=token,
            json=self._field_definition(
                field_name=field_name,
                field_type=field_type,
                ui_type=ui_type,
                field_property=field_property,
            ),
        )
        return parse_feishu_field_metadata(data.get("field"))

    async def update_field_definition(
        self,
        field_id: str,
        *,
        field_name: str,
        field_type: int,
        ui_type: str,
        field_property: dict[str, object],
    ) -> FeishuFieldMetadata:
        if not field_id:
            raise ValueError("Feishu field_id cannot be blank.")
        token = await self.tenant_access_token()
        data = await self._request(
            "PUT",
            f"{self._field_path()}/{field_id}",
            token=token,
            json=self._field_definition(
                field_name=field_name,
                field_type=field_type,
                ui_type=ui_type,
                field_property=field_property,
            ),
        )
        return parse_feishu_field_metadata(data.get("field"))

    @staticmethod
    def _field_definition(
        *,
        field_name: str,
        field_type: int,
        ui_type: str,
        field_property: dict[str, object],
    ) -> dict[str, object]:
        if (
            not field_name
            or isinstance(field_type, bool)
            or field_type <= 0
            or not ui_type
            or not isinstance(field_property, dict)
        ):
            raise ValueError("Feishu field definition is invalid.")
        definition: dict[str, object] = {
            "field_name": field_name,
            "type": field_type,
            "ui_type": ui_type,
        }
        if field_property:
            definition["property"] = dict(field_property)
        return definition

    def _record_path(self, record_id: str | None = None) -> str:
        path = (
            f"/open-apis/bitable/v1/apps/{self._base_token}/tables/"
            f"{self._table_id}/records"
        )
        return f"{path}/{record_id}" if record_id else path

    async def create_record(self, fields: dict[str, Any]) -> str:
        unknown = set(fields) - SYSTEM_FIELDS - BUSINESS_FIELDS
        if unknown:
            raise ValueError(f"Unsupported Feishu fields: {sorted(unknown)}")
        data = await self._feishu.create_record(
            self._base_token, self._table_id, fields
        )
        record = data.get("record")
        record_id = record.get("record_id") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or not record_id:
            raise FeishuSampleError("Feishu create response is missing record_id.")
        return record_id

    async def get_record(self, record_id: str) -> dict[str, Any]:
        return (await self.get_record_snapshot(record_id)).fields

    async def get_record_snapshot(self, record_id: str) -> FeishuRecordSnapshot:
        data = await self._feishu.get_record(
            self._base_token, self._table_id, record_id
        )
        record = data.get("record")
        return parse_feishu_record_snapshot(record)

    async def find_record_by_sync_key(
        self, sync_key: str
    ) -> tuple[str, dict[str, Any]] | None:
        mapping = await self.list_record_sync_key_map()
        record_id = mapping.get(sync_key)
        if record_id is None:
            return None
        return record_id, await self.get_record(record_id)

    async def list_record_sync_key_map(self) -> dict[str, str]:
        async def fetch_page(page_token: str | None) -> dict[str, Any]:
            params: dict[str, object] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            return await self._feishu.list_records(
                self._base_token, self._table_id, params=params
            )

        return await build_record_sync_key_map(fetch_page)

    async def update_business_fields(
        self, record_id: str, fields: dict[str, Any]
    ) -> None:
        if not fields or not set(fields) <= BUSINESS_FIELDS:
            raise ValueError("Only non-empty Feishu business fields are allowed.")
        await self._feishu.update_record(
            self._base_token, self._table_id, record_id, fields
        )

    async def update_system_fields(
        self, record_id: str, fields: dict[str, Any]
    ) -> None:
        if not fields or not set(fields) <= SYSTEM_FIELDS:
            raise ValueError("Only non-empty Feishu system fields are allowed.")
        await self._feishu.update_record(
            self._base_token, self._table_id, record_id, fields
        )
