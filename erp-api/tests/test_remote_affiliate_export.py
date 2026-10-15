import hashlib
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from erp_api.routers.remote_affiliate_export import router
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.remote_affiliate_export import (
    RemoteAffiliateExportManifest,
    map_validated_export,
)
from tests.test_affiliate_creator_export_parser import HEADERS, _xlsx_bytes


def _manifest(content: bytes, *, source_total: int = 1):
    return RemoteAffiliateExportManifest(
        capture_id=uuid4(),
        shop_id=uuid4(),
        platform_shop_id="shop-1",
        environment_id="123456789",
        resource="creators",
        window_start=date(2026, 10, 7),
        window_end=date(2026, 10, 7),
        observed_at=datetime(2026, 10, 9, tzinfo=UTC),
        request_id="export-request-1",
        source_total=source_total,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )


def _query(manifest):
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=manifest.shop_id,
        window_start=manifest.window_start,
        window_end=manifest.window_end,
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_export_rejects_missing_creator_rows_before_write() -> None:
    content = _xlsx_bytes(HEADERS, (("creator_one",) + ("0",) * (len(HEADERS) - 1),))
    manifest = _manifest(content, source_total=2)
    with pytest.raises(ValueError, match="source total"):
        map_validated_export(manifest, content, _query(manifest))


def test_export_rejects_changed_file_hash() -> None:
    content = _xlsx_bytes(HEADERS, (("creator_one",) + ("0",) * (len(HEADERS) - 1),))
    manifest = _manifest(content)
    with pytest.raises(ValueError, match="digest"):
        map_validated_export(manifest, content + b"changed", _query(manifest))


def test_export_accepts_complete_creator_workbook() -> None:
    content = _xlsx_bytes(HEADERS, (("creator_one",) + ("0",) * (len(HEADERS) - 1),))
    manifest = _manifest(content)
    page, summary = map_validated_export(manifest, content, _query(manifest))
    assert page.source_kind == "browser_export"
    assert summary["records_unique"] == 1


def test_export_ingress_requires_token_before_reading_workbook() -> None:
    app = FastAPI()
    app.state.settings = type("Settings", (), {
        "affiliate_capture_service_token": SecretStr("a" * 40),
        "affiliate_export_tenant_id": uuid4(),
    })()
    app.include_router(router)
    response = TestClient(app).post("/internal/affiliate-exports/workbooks", content=b"bad")
    assert response.status_code == 401
