from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from erp_api.services.logistics_document_repository import (
    LogisticsDocumentRepository,
)
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingValidationError,
)
from erp_api.services.object_storage import ObjectStorage

ALLOWED_CONTENT_TYPES = {
    "shipping_label": {"application/pdf", "image/png", "text/plain"},
    "carrier_invoice": {
        "application/pdf",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "return_proof": {"application/pdf", "image/png", "image/jpeg"},
}
OWNER_TYPES = {
    "shipping_label": "waybill",
    "carrier_invoice": "carrier_invoice",
    "return_proof": "return",
}


class LogisticsDocumentService:
    def __init__(
        self,
        repository: LogisticsDocumentRepository,
        storage: ObjectStorage,
        *,
        max_bytes: int,
        presigned_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._max_bytes = max_bytes
        self._presigned_ttl_seconds = presigned_ttl_seconds

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    async def upload(
        self,
        tenant_id: UUID,
        *,
        document_type: str,
        owner_reference_id: UUID,
        filename: str,
        content_type: str,
        body: bytes,
        actor_user_id: UUID,
    ) -> dict[str, object]:
        self._validate(document_type, content_type, body)
        document_id = uuid4()
        suffix = _safe_suffix(filename)
        object_key = (
            f"tenants/{tenant_id}/logistics/{document_type}/"
            f"{owner_reference_id}/{document_id}{suffix}"
        )
        digest = sha256(body).hexdigest()
        await self._storage.put(
            object_key,
            body,
            content_type=content_type,
            metadata={
                "document-id": str(document_id),
                "sha256": digest,
                "tenant-id": str(tenant_id),
            },
        )
        try:
            record = await self._repository.create(
                tenant_id,
                document_id=document_id,
                document_type=document_type,
                owner_type=OWNER_TYPES[document_type],
                owner_reference_id=owner_reference_id,
                storage_provider=self._storage.provider,
                bucket=self._storage.bucket,
                object_key=object_key,
                original_filename=Path(filename).name[:255] or "document",
                content_type=content_type,
                size_bytes=len(body),
                sha256_hex=digest,
                actor_user_id=actor_user_id,
            )
        except Exception:
            await self._storage.delete(object_key)
            raise
        return await self._with_url(record)

    async def get_current(
        self, tenant_id: UUID, document_type: str, owner_reference_id: UUID
    ) -> dict[str, object]:
        record = await self._repository.get_current(
            tenant_id, document_type, owner_reference_id
        )
        return await self._with_url(record)

    def _validate(self, document_type: str, content_type: str, body: bytes) -> None:
        if document_type not in ALLOWED_CONTENT_TYPES:
            raise LogisticsShippingValidationError("Unsupported document type.")
        if content_type not in ALLOWED_CONTENT_TYPES[document_type]:
            raise LogisticsShippingValidationError("Unsupported document content type.")
        if not body:
            raise LogisticsShippingValidationError("Document cannot be empty.")
        if len(body) > self._max_bytes:
            raise LogisticsShippingValidationError("Document exceeds the size limit.")

    async def _with_url(self, record: dict[str, object]) -> dict[str, object]:
        return {key: value for key, value in record.items() if key != "objectKey"} | {
            "downloadUrl": await self._storage.presign_get(
                str(record["objectKey"]), expires_seconds=self._presigned_ttl_seconds
            ),
            "expiresInSeconds": self._presigned_ttl_seconds,
        }


def _safe_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix and len(suffix) <= 10 and suffix[1:].isalnum():
        return suffix
    return ""
