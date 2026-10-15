from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.logistics_document_service import LogisticsDocumentService
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingValidationError,
)


class FakeStorage:
    provider = "s3"
    bucket = "erp-documents"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key, body, **kwargs):
        self.objects[key] = body

    async def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def presign_get(self, key, **kwargs):
        return f"https://objects.test/{key}?signed=1"


class FakeRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.record: dict[str, object] | None = None

    async def create(self, tenant_id, **kwargs):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.record = {
            "id": kwargs["document_id"],
            "documentType": kwargs["document_type"],
            "ownerType": kwargs["owner_type"],
            "ownerReferenceId": kwargs["owner_reference_id"],
            "originalFilename": kwargs["original_filename"],
            "contentType": kwargs["content_type"],
            "sizeBytes": kwargs["size_bytes"],
            "sha256Hex": kwargs["sha256_hex"],
            "isCurrent": True,
            "createdByUserId": kwargs["actor_user_id"],
            "createdAt": datetime(2026, 8, 24, tzinfo=UTC),
            "objectKey": kwargs["object_key"],
        }
        return self.record

    async def get_current(self, tenant_id, document_type, owner_reference_id):
        return self.record


@pytest.mark.asyncio
async def test_document_service_uploads_hashes_and_returns_short_lived_url() -> None:
    repository, storage = FakeRepository(), FakeStorage()
    service = LogisticsDocumentService(
        repository, storage, max_bytes=1024, presigned_ttl_seconds=900
    )
    owner_id = uuid4()

    record = await service.upload(
        uuid4(),
        document_type="shipping_label",
        owner_reference_id=owner_id,
        filename="label.pdf",
        content_type="application/pdf",
        body=b"%PDF-test",
        actor_user_id=uuid4(),
    )

    assert record["documentType"] == "shipping_label"
    assert record["downloadUrl"].startswith("https://objects.test/")
    assert record["expiresInSeconds"] == 900
    assert storage.objects
    assert "objectKey" not in record


@pytest.mark.asyncio
async def test_document_service_rejects_wrong_type_and_deletes_orphan_on_db_error() -> (
    None
):
    storage = FakeStorage()
    invalid = LogisticsDocumentService(
        FakeRepository(), storage, max_bytes=5, presigned_ttl_seconds=900
    )
    with pytest.raises(LogisticsShippingValidationError):
        await invalid.upload(
            uuid4(),
            document_type="return_proof",
            owner_reference_id=uuid4(),
            filename="proof.exe",
            content_type="application/octet-stream",
            body=b"bad",
            actor_user_id=uuid4(),
        )

    failing = LogisticsDocumentService(
        FakeRepository(fail=True), storage, max_bytes=1024, presigned_ttl_seconds=900
    )
    with pytest.raises(RuntimeError):
        await failing.upload(
            uuid4(),
            document_type="carrier_invoice",
            owner_reference_id=uuid4(),
            filename="invoice.csv",
            content_type="text/csv",
            body=b"amount\n100",
            actor_user_id=uuid4(),
        )
    assert storage.deleted
