from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import (
    LOGISTICS_COST_RECONCILE,
    LOGISTICS_DISPATCH,
    LOGISTICS_VIEW,
    RETURNS_MANAGE,
    RETURNS_VIEW,
)
from erp_api.routers import logistics, logistics_documents
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeDocumentService:
    max_bytes = 1024

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def upload(self, tenant_id: UUID, **kwargs):
        self.calls.append(("upload", kwargs))
        return _document(kwargs["document_type"], kwargs["owner_reference_id"])

    async def get_current(
        self, tenant_id: UUID, document_type: str, owner_reference_id: UUID
    ):
        self.calls.append(("get", {"document_type": document_type}))
        return _document(document_type, owner_reference_id)


def _client(permissions: list[str]):
    service = FakeDocumentService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Operator",
        username="operator",
        roles=[],
        permissions=permissions,
    )
    app.dependency_overrides[logistics_documents._service] = lambda: service
    return TestClient(app), service


def test_dispatcher_uploads_and_reads_waybill_label_as_object_document() -> None:
    waybill_id = uuid4()
    client, service = _client([LOGISTICS_VIEW, LOGISTICS_DISPATCH])
    with client:
        uploaded = client.post(
            f"/api/logistics/waybills/{waybill_id}/label",
            files={"file": ("label.pdf", b"%PDF-test", "application/pdf")},
        )
        loaded = client.get(f"/api/logistics/waybills/{waybill_id}/label")

    assert uploaded.status_code == 200
    assert uploaded.json()["documentType"] == "shipping_label"
    assert loaded.json()["downloadUrl"].startswith("https://objects.test/")
    assert service.calls[0][1]["body"] == b"%PDF-test"


def test_invoice_and_return_uploads_use_separate_permissions() -> None:
    invoice_client, _ = _client([LOGISTICS_VIEW, LOGISTICS_COST_RECONCILE])
    return_client, _ = _client([RETURNS_VIEW, RETURNS_MANAGE])
    with invoice_client:
        invoice = invoice_client.post(
            f"/api/logistics/carrier-invoices/{uuid4()}/document",
            files={"file": ("invoice.csv", b"amount\n100", "text/csv")},
        )
    with return_client:
        proof = return_client.post(
            f"/api/logistics/return-proofs/{uuid4()}/document",
            files={"file": ("proof.jpg", b"jpeg", "image/jpeg")},
        )

    assert invoice.json()["documentType"] == "carrier_invoice"
    assert proof.json()["documentType"] == "return_proof"


def test_document_upload_rejects_missing_domain_permission() -> None:
    client, service = _client([LOGISTICS_VIEW])
    with client:
        response = client.post(
            f"/api/logistics/waybills/{uuid4()}/label",
            files={"file": ("label.pdf", b"%PDF", "application/pdf")},
        )
    assert response.status_code == 403
    assert service.calls == []


def _document(document_type: str, owner_id: UUID) -> dict[str, object]:
    return {
        "id": uuid4(),
        "documentType": document_type,
        "ownerType": {
            "shipping_label": "waybill",
            "carrier_invoice": "carrier_invoice",
            "return_proof": "return",
        }[document_type],
        "ownerReferenceId": owner_id,
        "originalFilename": "document.pdf",
        "contentType": "application/pdf",
        "sizeBytes": 9,
        "sha256Hex": "a" * 64,
        "isCurrent": True,
        "createdByUserId": uuid4(),
        "createdAt": datetime(2026, 8, 24, tzinfo=UTC),
        "downloadUrl": "https://objects.test/document?signed=1",
        "expiresInSeconds": 900,
    }
