"""A scoped Bitable client using the existing shared token and rate limiter."""
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_table_mirror_client import FeishuTableMirrorClient
from erp_api.services.logistics_feishu_fields import OWNED_FIELDS, field_definition


class LogisticsFeishuClient(FeishuTableMirrorClient):
    def __init__(self, **kwargs):
        super().__init__(writable_fields=OWNED_FIELDS, **kwargs)

    async def validate_schema(self):
        fields = await self.list_field_metadata()
        for name in OWNED_FIELDS:
            if name not in fields or fields[name].field_type != field_definition(name)["type"]:
                raise FeishuSampleError("Logistics Feishu schema does not match the approved fields")
        return fields

    async def create_idempotent(self, rows, client_token):
        self._validate_rows(rows)
        token = await self.tenant_access_token()
        data = await self._request(
            "POST", self._record_path() + "/batch_create", token=token, retry_mode="idempotent",
            params={"client_token": client_token}, json={"records": [{"fields": row} for row in rows]},
        )
        return self._validate_response_count(data, len(rows), "create")
