from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_document import LogisticsDocument
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingNotFoundError,
)


class LogisticsDocumentRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        tenant_id: UUID,
        *,
        document_id: UUID,
        document_type: str,
        owner_type: str,
        owner_reference_id: UUID,
        storage_provider: str,
        bucket: str,
        object_key: str,
        original_filename: str,
        content_type: str,
        size_bytes: int,
        sha256_hex: str,
        actor_user_id: UUID,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            waybill_id = owner_reference_id if owner_type == "waybill" else None
            if waybill_id is not None:
                waybill = await session.get(
                    LogisticsWaybill, waybill_id, with_for_update=True
                )
                if waybill is None:
                    raise LogisticsShippingNotFoundError("Waybill was not found.")
                if waybill.status == "cancelled":
                    raise LogisticsShippingNotFoundError(
                        "Cancelled waybill cannot receive a label."
                    )
                if waybill.status == "created":
                    waybill.status = "label_ready"
            await session.execute(
                update(LogisticsDocument)
                .where(
                    LogisticsDocument.document_type == document_type,
                    LogisticsDocument.owner_reference_id == owner_reference_id,
                    LogisticsDocument.is_current.is_(True),
                )
                .values(is_current=False)
            )
            document = LogisticsDocument(
                id=document_id,
                tenant_id=tenant_id,
                document_type=document_type,
                owner_type=owner_type,
                owner_reference_id=owner_reference_id,
                waybill_id=waybill_id,
                storage_provider=storage_provider,
                bucket=bucket,
                object_key=object_key,
                original_filename=original_filename,
                content_type=content_type,
                size_bytes=size_bytes,
                sha256_hex=sha256_hex,
                is_current=True,
                created_by_user_id=actor_user_id,
            )
            session.add(document)
            await session.commit()
            await session.refresh(document)
            return _record(document)
        raise RuntimeError("Tenant database session was not created.")

    async def get_current(
        self, tenant_id: UUID, document_type: str, owner_reference_id: UUID
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            document = await session.scalar(
                select(LogisticsDocument).where(
                    LogisticsDocument.document_type == document_type,
                    LogisticsDocument.owner_reference_id == owner_reference_id,
                    LogisticsDocument.is_current.is_(True),
                )
            )
            if document is None:
                raise LogisticsShippingNotFoundError("Document was not found.")
            return _record(document)
        raise RuntimeError("Tenant database session was not created.")


def _record(document: LogisticsDocument) -> dict[str, object]:
    return {
        "id": document.id,
        "documentType": document.document_type,
        "ownerType": document.owner_type,
        "ownerReferenceId": document.owner_reference_id,
        "originalFilename": document.original_filename,
        "contentType": document.content_type,
        "sizeBytes": document.size_bytes,
        "sha256Hex": document.sha256_hex,
        "isCurrent": document.is_current,
        "createdByUserId": document.created_by_user_id,
        "createdAt": document.created_at,
        "objectKey": document.object_key,
    }
