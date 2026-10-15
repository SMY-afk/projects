from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from erp_api.routers import remote_affiliate_export as ingress


def _app(shop_id, *, active=True):
    app = FastAPI()
    app.state.settings = type(
        "Settings",
        (),
        {
            "affiliate_capture_service_token": SecretStr("a" * 40),
            "affiliate_export_tenant_id": uuid4(),
        },
    )()

    class Session:
        async def scalar(self, _statement):
            return shop_id if active else None

    class Database:
        @asynccontextmanager
        async def system_session_factory(self):
            yield Session()

    app.state.database = Database()
    app.state.arq_queue = object()
    app.include_router(ingress.router)
    return app


def _report(shop_id, *, age_seconds=0, state="online", dates=None):
    return {
        "shop_id": str(shop_id),
        "platform_shop_id": "9768147009521852682",
        "state": state,
        "observed_at": (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat(),
        "dates": dates or [],
    }


def test_health_ingress_requires_token_before_parsing_body() -> None:
    response = TestClient(_app(uuid4())).post(
        "/internal/affiliate-exports/health", content=b"not json"
    )
    assert response.status_code == 401


def test_health_ingress_rejects_stale_and_wrong_shop() -> None:
    shop_id = uuid4()
    token = {"x-erp-affiliate-capture-token": "a" * 40}
    client = TestClient(_app(shop_id, active=False))
    assert client.post(
        "/internal/affiliate-exports/health",
        headers=token,
        json=_report(shop_id, age_seconds=61),
    ).status_code == 422
    assert client.post(
        "/internal/affiliate-exports/health",
        headers=token,
        json=_report(shop_id),
    ).status_code == 409


def test_health_ingress_preserves_direct_timestamp_and_rejects_regression(
    monkeypatch,
) -> None:
    shop_id = uuid4()
    direct_at = datetime.now(UTC) - timedelta(minutes=4)
    calls = []

    class Repository:
        def __init__(self, _redis):
            pass

        async def observed_evidence_for(self, *_args, **_kwargs):
            return date(2026, 10, 8), direct_at + timedelta(minutes=1)

        async def record_observation(self, *_args, **kwargs):
            calls.append(("date", kwargs["now"]))

        async def record(self, *_args):
            calls.append(("health", None))

    monkeypatch.setattr(ingress, "AffiliateCaptureHealthRepository", Repository)
    client = TestClient(_app(shop_id))
    payload = _report(
        shop_id,
        dates=[{
            "resource": "creators",
            "latest_available_date": "2026-10-07",
            "observed_at": direct_at.isoformat(),
        }],
    )
    response = client.post(
        "/internal/affiliate-exports/health",
        headers={"x-erp-affiliate-capture-token": "a" * 40},
        json=payload,
    )
    assert response.status_code == 409
    assert calls == []


def test_health_ingress_records_fresh_direct_date_without_retimestamping(
    monkeypatch,
) -> None:
    shop_id = uuid4()
    direct_at = datetime.now(UTC) - timedelta(minutes=4)
    calls = []

    class Repository:
        def __init__(self, _redis):
            pass

        async def observed_evidence_for(self, *_args):
            return None

        async def record_observation(self, *_args, **kwargs):
            calls.append(("date", kwargs["now"]))

        async def record(self, *_args):
            calls.append(("health", None))

    monkeypatch.setattr(ingress, "AffiliateCaptureHealthRepository", Repository)
    response = TestClient(_app(shop_id)).post(
        "/internal/affiliate-exports/health",
        headers={"x-erp-affiliate-capture-token": "a" * 40},
        json=_report(
            shop_id,
            dates=[{
                "resource": "creators",
                "latest_available_date": "2026-10-08",
                "observed_at": direct_at.isoformat(),
            }],
        ),
    )
    assert response.status_code == 202
    assert calls == [("date", direct_at), ("health", None)]
