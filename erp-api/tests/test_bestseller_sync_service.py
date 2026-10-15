from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from erp_api.services.bestseller_sync_service import (
    BestsellerSyncError,
    BestsellerSyncService,
)
from erp_api.services.tiktok_bestseller_schemas import TikTokBestsellerPage
from erp_api.services.tiktok_transport import TikTokApiError, TikTokRateLimitError


class FakeShopRepository:
    async def get_authorized_tiktok_shop(self, tenant_id, shop_id=None):
        return {
            "id": shop_id,
            "timezone": "America/Los_Angeles",
            "platform_shop_id": "shop-1",
        }

    async def get_access_token(self, tenant_id, shop_id):
        return "access-token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "shop-cipher"


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def __getattr__(self, name):
        if not name.startswith("list_"):
            raise AttributeError(name)

        async def call(access_token, **kwargs):
            self.calls.append((name, access_token, kwargs))
            return TikTokBestsellerPage([], f"request-{name}")

        return call


class FakeRepository:
    def __init__(self) -> None:
        self.calls = []
        self.stale_calls = []

    async def replace_snapshot(self, tenant_id, query, page):
        self.calls.append((tenant_id, query, page))
        return uuid4()

    async def mark_snapshot_stale(self, tenant_id, query, error_category):
        self.stale_calls.append((tenant_id, query, error_category))
        return True


def _service():
    client = FakeClient()
    repository = FakeRepository()
    service = BestsellerSyncService(
        repository,
        FakeShopRepository(),
        client,
        clock=lambda: datetime(2026, 8, 21, 6, tzinfo=UTC),
    )
    return service, client, repository


@pytest.mark.parametrize(
    ("entity_type", "method_name", "author_type"),
    [
        ("product", "list_products", None),
        ("creator", "list_creators", "ALL"),
        ("video", "list_videos", None),
        ("live", "list_lives", None),
    ],
)
def test_sync_fetches_and_replaces_exactly_one_requested_window(
    entity_type: str,
    method_name: str,
    author_type: str | None,
) -> None:
    service, client, repository = _service()
    tenant_id, shop_id = uuid4(), uuid4()

    result = asyncio.run(
        service.sync(
            tenant_id,
            shop_id=shop_id,
            entity_type=entity_type,
            reference_date=date(2026, 7, 1),
            time_slot="30D",
            currency="USD",
            author_type=author_type,
        )
    )

    assert result.entry_count == 0
    assert len(client.calls) == 1
    assert client.calls[0][0] == method_name
    assert client.calls[0][1] == "access-token"
    assert client.calls[0][2]["date"] == "2026-07-01"
    assert client.calls[0][2]["time_slot"] == "30D"
    assert client.calls[0][2].get("author_type") == author_type
    assert len(repository.calls) == 1
    assert repository.calls[0][1].reference_date == date(2026, 7, 1)


def test_sync_rejects_incomplete_or_future_dates_without_api_calls() -> None:
    service, client, repository = _service()

    with pytest.raises(ValueError, match="completed"):
        asyncio.run(
            service.sync(
                uuid4(),
                shop_id=uuid4(),
                entity_type="product",
                reference_date=date(2026, 8, 20),
                time_slot="1D",
                currency="USD",
            )
        )

    assert client.calls == []
    assert repository.calls == []


def test_sync_requires_authorized_credentials() -> None:
    class MissingCredentialsShopRepository(FakeShopRepository):
        async def get_access_token(self, tenant_id, shop_id):
            return None

    shop_repository = MissingCredentialsShopRepository()
    service = BestsellerSyncService(FakeRepository(), shop_repository, FakeClient())

    with pytest.raises(RuntimeError, match="credentials"):
        asyncio.run(
            service.sync(
                uuid4(),
                shop_id=uuid4(),
                entity_type="product",
                reference_date=date(2026, 7, 1),
                time_slot="1D",
                currency="USD",
            )
        )


@pytest.mark.parametrize(
    ("upstream_error", "category", "retryable", "retry_after_seconds"),
    [
        (
            TikTokApiError(
                "Authorization expired.",
                code="105005",
                status_code=502,
                request_id="request-auth",
            ),
            "reauthorization_required",
            False,
            None,
        ),
        (
            TikTokRateLimitError(
                retry_after_seconds=7,
                request_id="request-rate-limit",
            ),
            "rate_limited",
            True,
            7,
        ),
    ],
)
def test_sync_marks_last_success_stale_and_keeps_error_categories_distinct(
    upstream_error,
    category: str,
    retryable: bool,
    retry_after_seconds: float | None,
) -> None:
    class FailingClient(FakeClient):
        async def list_products(self, access_token, **kwargs):
            raise upstream_error

    repository = FakeRepository()
    service = BestsellerSyncService(
        repository,
        FakeShopRepository(),
        FailingClient(),
        clock=lambda: datetime(2026, 8, 21, 6, tzinfo=UTC),
    )
    tenant_id, shop_id = uuid4(), uuid4()

    with pytest.raises(BestsellerSyncError) as captured:
        asyncio.run(
            service.sync(
                tenant_id,
                shop_id=shop_id,
                entity_type="product",
                reference_date=date(2026, 8, 19),
                time_slot="1D",
                currency="USD",
            )
        )

    assert captured.value.category == category
    assert captured.value.retryable is retryable
    assert captured.value.retry_after_seconds == retry_after_seconds
    assert captured.value.snapshot_marked_stale is True
    assert repository.calls == []
    assert len(repository.stale_calls) == 1
    assert repository.stale_calls[0][2] == category
