from __future__ import annotations

import gzip
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from erp_api.core.errors import register_exception_handlers
from erp_api.routers.remote_sample_capture import router
from erp_api.services.remote_sample_capture import (
    RemoteSampleBatch,
    RemoteSamplePage,
    parse_complete_batch,
)


def _page(application_id: str, next_token: str | None, total: int) -> RemoteSamplePage:
    return RemoteSamplePage(
        payload={
            "data": {
                "sample_applications": [
                    {
                        "id": application_id,
                        "status": "PENDING",
                        "creator": {"id": "creator-1"},
                        "product": {"id": "product-1"},
                    }
                ],
                "next_page_token": next_token,
                "total_count": total,
            }
        },
        request_id=f"request-{application_id}",
        observed_at=datetime(2026, 10, 9, 1, 0, tzinfo=UTC),
    )


def _batch(pages: list[RemoteSamplePage]) -> RemoteSampleBatch:
    return RemoteSampleBatch(
        capture_id=uuid4(),
        shop_id=uuid4(),
        environment_id="1234567890",
        platform_shop_id="shop-1",
        pages=pages,
    )


def test_full_raw_batch_has_stable_digest() -> None:
    batch = _batch([_page("a", "next", 2), _page("b", None, 2)])
    pages, digest = parse_complete_batch(batch)
    assert len(pages) == 2
    assert len(digest or "") == 64
    assert (
        parse_complete_batch(
            RemoteSampleBatch.model_validate_json(batch.model_dump_json())
        )[1]
        == digest
    )


@pytest.mark.parametrize(
    "pages",
    [
        [_page("a", "next", 1)],
        [_page("a", None, 2)],
        [_page("a", None, 2), _page("b", None, 2)],
    ],
)
def test_incomplete_or_inconsistent_batch_is_rejected(pages) -> None:
    with pytest.raises(ValueError):
        parse_complete_batch(_batch(pages))


def test_naive_observation_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RemoteSamplePage(
            payload={},
            request_id="request",
            observed_at=datetime.fromisoformat("2026-10-09T01:00:00"),
        )


def test_ingress_rejects_missing_token_before_parsing() -> None:
    app = FastAPI()
    app.state.settings = type(
        "Settings",
        (),
        {
            "sample_capture_service_token": SecretStr("a" * 40),
            "affiliate_export_tenant_id": uuid4(),
        },
    )()
    app.include_router(router)
    response = TestClient(app).post("/internal/sample-captures/batches", content=b"{}")
    assert response.status_code == 401
    assert "a" * 40 not in response.text


def test_ingress_rejects_incomplete_batch_before_database() -> None:
    app = FastAPI()
    app.state.settings = type(
        "Settings",
        (),
        {
            "sample_capture_service_token": SecretStr("a" * 40),
            "affiliate_export_tenant_id": uuid4(),
        },
    )()
    app.include_router(router)
    response = TestClient(app).post(
        "/internal/sample-captures/batches",
        headers={"x-erp-capture-token": "a" * 40},
        content=_batch([_page("a", "next", 1)]).model_dump_json(),
    )
    assert response.status_code == 422


def test_gzip_ingress_rejects_incomplete_batch_before_database() -> None:
    app = FastAPI()
    app.state.settings = type(
        "Settings",
        (),
        {
            "sample_capture_service_token": SecretStr("a" * 40),
            "affiliate_export_tenant_id": uuid4(),
        },
    )()
    app.include_router(router)
    response = TestClient(app).post(
        "/internal/sample-captures/batches",
        headers={
            "x-erp-capture-token": "a" * 40,
            "content-encoding": "gzip",
        },
        content=gzip.compress(
            _batch([_page("a", "next", 1)]).model_dump_json().encode()
        ),
    )
    assert response.status_code == 422


def test_ingress_conflict_keeps_safe_recovery_code_with_shared_error_handler(monkeypatch):
    class Lock:
        def __init__(self, _database):
            pass

        @asynccontextmanager
        async def acquire(self, *_):
            yield False

    monkeypatch.setattr("erp_api.routers.remote_sample_capture.SampleShopSyncLock", Lock)
    app = FastAPI()
    app.state.settings = type("Settings", (), {
        "sample_capture_service_token": SecretStr("a" * 40),
        "affiliate_export_tenant_id": uuid4(),
    })()
    app.state.database = object()
    app.include_router(router)
    register_exception_handlers(app)
    response = TestClient(app).post(
        "/internal/sample-captures/batches", headers={"x-erp-capture-token": "a" * 40},
        content=_batch([_page("a", None, 1)]).model_dump_json(),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert response.headers.get("x-erp-capture-error") == "busy"
