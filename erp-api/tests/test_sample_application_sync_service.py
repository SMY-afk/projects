from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.sample_application_sync_service import (
    SampleApplicationSyncService,
)
from erp_api.services.tiktok_sample_application_client import (
    TikTokCreatorPerformance,
)
from erp_api.services.tiktok_transport import TikTokApiError


class FakeAudits:
    def __init__(self) -> None:
        self.batch_id = uuid4()
        self.run_id = uuid4()
        self.finished: dict[str, object] | None = None

    async def start(self, **kwargs):
        return self.batch_id, self.run_id

    async def finish(self, **kwargs):
        self.finished = kwargs


class FakeApplications:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def upsert_source_payloads(self, **kwargs):
        self.calls.append(kwargs)
        return tuple(uuid4() for _ in kwargs["observations"])


class FakeShops:
    async def get_access_token(self, tenant_id, shop_id):
        return "secret-access-token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "secret-shop-cipher"


class FakeClient:
    def __init__(self, *, fail_after_page: bool = False) -> None:
        self.fail_after_page = fail_after_page

    async def iter_pages(self, access_token, **kwargs):
        yield SimpleNamespace(
            applications=(
                {
                    "id": "sample-1",
                    "status": "PENDING",
                    "creator": {
                        "creator_open_id": "creator-1",
                        "avatar_url": (
                            "https://p16-common-sign.tiktokcdn-us.com/avatar.jpg"
                            "?refresh_token=private&x-signature=private"
                        ),
                        "cookie": "must-not-persist",
                    },
                    "product": {"shop_cipher": "must-not-persist"},
                    "token": "must-not-persist",
                },
            ),
            total_count=1,
            platform_request_id="request-1",
        )
        if self.fail_after_page:
            raise TikTokApiError(
                "pagination incomplete",
                code="pagination_incomplete",
                status_code=502,
            )

    async def get_creator_performance(self, access_token, **kwargs):
        return TikTokCreatorPerformance(
            fields={
                "post_rate": "5171",
                "avg_ec_video_play_count": 1200,
                "units_sold": 614,
            },
            platform_request_id="performance-request-1",
            cache_hit=False,
        )


def _service(*, fail_after_page: bool = False):
    audits = FakeAudits()
    applications = FakeApplications()
    service = SampleApplicationSyncService(
        audits,
        applications,
        FakeShops(),
        FakeClient(fail_after_page=fail_after_page),
    )
    return service, audits, applications


def test_sync_persists_request_id_and_completeness_without_secrets() -> None:
    service, audits, applications = _service()
    result = asyncio.run(
        service.sync(uuid4(), uuid4(), mode="active", status="PENDING")
    )

    assert result.status == "succeeded"
    assert result.request_ids == ("request-1", "performance-request-1")
    assert not hasattr(result, "raw_payload")
    assert len(applications.calls) == 1
    observations = applications.calls[0]["observations"]
    assert observations[0].request_id == "request-1"
    assert observations[0].source_capture_id == audits.batch_id
    assert "token" not in observations[0].payload
    assert "cookie" not in observations[0].payload["creator"]
    assert "shop_cipher" not in observations[0].payload["product"]
    assert applications.calls[0]["source_type"] == "official_api"
    assert observations[0].payload["creator"]["performance"]["units_sold"] == 614
    assert observations[0].payload["creator"]["avatar_url"].endswith("/avatar.jpg")
    assert "refresh_token" not in repr(observations[0].payload)
    assert result.avatar_stored_count == 0
    assert result.avatar_error_count == 0
    assert audits.finished is not None
    assert audits.finished["request_ids"] == [
        "request-1",
        "performance-request-1",
    ]
    audit_text = repr(audits.finished)
    assert "secret-access-token" not in audit_text
    assert "secret-shop-cipher" not in audit_text


def test_incomplete_pagination_does_not_overwrite_last_successful_data() -> None:
    service, audits, applications = _service(fail_after_page=True)

    with pytest.raises(TikTokApiError, match="pagination incomplete"):
        asyncio.run(service.sync(uuid4(), uuid4(), mode="active", status="PENDING"))

    assert audits.finished is not None
    assert audits.finished["status"] == "partial"
    assert audits.finished["error_code"] == "pagination_incomplete"
    assert audits.finished["error_summary"] == (
        "Sample application sync did not complete."
    )
    assert applications.calls == []


@pytest.mark.parametrize(
    ("mode", "status"),
    [("active", "COMPLETED"), ("terminal", "PENDING"), ("full", "PENDING")],
)
def test_sync_rejects_cross_schedule_statuses(mode: str, status: str) -> None:
    service, _, _ = _service()
    with pytest.raises(ValueError, match="scope is invalid"):
        asyncio.run(service.sync(uuid4(), uuid4(), mode=mode, status=status))
