import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from erp_api.routers import remote_affiliate_capture
from erp_api.routers.remote_affiliate_capture import router
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliatePaginationDTO,
)
from erp_api.services.remote_affiliate_capture import (
    RemoteAffiliateBatch,
    validate_mapped_batch,
)


def _batch(*, resource="creators", pages=None):
    return RemoteAffiliateBatch(
        capture_id=uuid4(),
        shop_id=uuid4(),
        platform_shop_id="platform-shop-1",
        environment_id="123456",
        resource=resource,
        window_start=date(2026, 10, 7),
        window_end=date(2026, 10, 7),
        pages=pages or [
            {
                "page_number": 1,
                "next_page_number": None,
                "request_id": "request-1",
                "observed_at": datetime(2026, 10, 9, tzinfo=UTC),
                "payload": {"code": 0},
                "observation": {"pagination": {"mode": "page_page_size"}},
            }
        ],
    )


def _mapped(batch, *, page_number=1, next_cursor=None, total=1, records=()):
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource(batch.resource),
        shop_id=batch.shop_id,
        window_start=batch.window_start,
        window_end=batch.window_end,
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    return AffiliateCenterPageDTO(
        source_kind="page_capture",
        query=query,
        records=records,
        pagination=AffiliatePaginationDTO(
            mode="page_page_size",
            page_number=page_number,
            next_cursor=next_cursor,
            has_more=next_cursor is not None,
            total_count=total,
        ),
        request_id=f"request-{page_number}",
        source_updated_at=None,
        raw_payload={},
    )


def test_remote_affiliate_rejects_missing_middle_page() -> None:
    batch = _batch(pages=[
        {"page_number": 1, "next_page_number": 3, "request_id": "request-1",
         "observed_at": datetime(2026, 10, 9, tzinfo=UTC), "payload": {}, "observation": {}},
        {"page_number": 3, "next_page_number": None, "request_id": "request-3",
         "observed_at": datetime(2026, 10, 9, tzinfo=UTC), "payload": {}, "observation": {}},
    ])
    with pytest.raises(ValueError, match="contiguous"):
        validate_mapped_batch(batch, [_mapped(batch), _mapped(batch, page_number=3)])


def test_remote_affiliate_rejects_unconfirmed_terminal() -> None:
    batch = _batch(pages=[
        {"page_number": 1, "next_page_number": 2, "request_id": "request-1",
         "observed_at": datetime(2026, 10, 9, tzinfo=UTC), "payload": {}, "observation": {}},
    ])
    with pytest.raises(ValueError, match="terminal"):
        validate_mapped_batch(batch, [_mapped(batch, next_cursor="page:2")])


def test_remote_affiliate_rejects_total_mismatch() -> None:
    batch = _batch()
    with pytest.raises(ValueError, match="total"):
        validate_mapped_batch(batch, [_mapped(batch, total=2)])


def test_remote_affiliate_rejects_query_mismatch() -> None:
    batch = _batch()
    wrong = _batch()
    with pytest.raises(ValueError, match="query"):
        validate_mapped_batch(batch, [_mapped(wrong, total=0)])


def test_remote_affiliate_accepts_complete_empty_page() -> None:
    batch = _batch()
    assert validate_mapped_batch(batch, [_mapped(batch, total=0)]) == {
        "expected_total": 0,
        "pages_fetched": 1,
        "records_received": 0,
        "records_unique": 0,
        "duplicates": 0,
    }


def _client() -> TestClient:
    app = FastAPI()
    app.state.settings = type(
        "Settings", (), {
            "affiliate_capture_service_token": SecretStr("a" * 40),
            "affiliate_export_tenant_id": uuid4(),
        }
    )()
    app.include_router(router)
    return TestClient(app)


def test_remote_affiliate_ingress_requires_service_token() -> None:
    response = _client().post("/internal/affiliate-captures/batches", content=b"{}")
    assert response.status_code == 401
    assert "a" * 40 not in response.text


def test_remote_affiliate_ingress_rejects_bad_body_before_database() -> None:
    response = _client().post(
        "/internal/affiliate-captures/batches",
        content=b"{}",
        headers={"x-erp-affiliate-capture-token": "a" * 40},
    )
    assert response.status_code == 422


def test_remote_affiliate_ingress_returns_duplicate_receipt_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch()
    body = batch.model_dump_json().encode()
    existing = SimpleNamespace(
        job_id=f"remote-affiliate:{batch.capture_id}:{hashlib.sha256(body).hexdigest()}",
        status="succeeded",
        id=uuid4(),
    )

    @asynccontextmanager
    async def fake_lock(*_args):
        yield True

    async def fake_existing(*_args):
        return existing

    monkeypatch.setattr(remote_affiliate_capture, "_shop_lock", fake_lock)
    monkeypatch.setattr(remote_affiliate_capture, "_existing_run", fake_existing)
    client = _client()
    client.app.state.database = object()
    response = client.post(
        "/internal/affiliate-captures/batches",
        content=body,
        headers={"x-erp-affiliate-capture-token": "a" * 40},
    )
    assert response.status_code == 202
    assert response.json() == {
        "status": "stored", "duplicate": True, "run_id": str(existing.id)
    }
