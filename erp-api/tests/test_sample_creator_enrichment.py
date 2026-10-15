from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.services.sample_creator_avatar_storage import (
    SampleCreatorAvatarError,
    StoredCreatorAvatar,
)
from erp_api.services.sample_creator_enrichment import (
    SampleCreatorEnrichmentService,
)
from erp_api.services.tiktok_sample_application_client import (
    TikTokCreatorPerformance,
)
from erp_api.services.tiktok_transport import TikTokClientError, TikTokRateLimitError


class FakeClient:
    async def get_creator_performance(self, *_args, **_kwargs):
        return TikTokCreatorPerformance(
            fields={
                "sample_score": {"overall": "86"},
                "avatar_url": (
                    "https://p19-common-sign.tiktokcdn-us.com/new.jpg"
                    "?refresh_token=private"
                ),
            },
            platform_request_id="request-profile",
            cache_hit=False,
        )


class FakeAvatarStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sources = []

    async def store(self, source_url, **_kwargs):
        self.sources.append(source_url)
        if self.fail:
            raise SampleCreatorAvatarError("safe failure")
        return StoredCreatorAvatar(
            object_key="sample/creator-avatars/t/s/c/hash.jpg",
            source_hash="a" * 64,
        )


class FailingPerformanceClient:
    async def get_creator_performance(self, *_args, **_kwargs):
        raise TikTokClientError("TikTok request failed.")


class CountingPerformanceClient(FakeClient):
    def __init__(self) -> None:
        self.creator_ids = []

    async def get_creator_performance(self, *_args, **kwargs):
        self.creator_ids.append(kwargs["creator_open_id"])
        return await super().get_creator_performance(*_args, **kwargs)


class RateLimitedPerformanceClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get_creator_performance(self, *_args, **_kwargs):
        self.calls += 1
        raise TikTokRateLimitError(retry_after_seconds=30)


@pytest.mark.asyncio
async def test_enrichment_attaches_safe_avatar_reference_and_sanitized_profile() -> (
    None
):
    storage = FakeAvatarStorage()
    service = SampleCreatorEnrichmentService(FakeClient(), storage)
    payloads = [{"creator": {"creator_open_id": "creator-1"}, "product": {}}]
    result = await service.enrich(
        payloads,
        source_payloads=(
            {
                "creator": {
                    "creator_open_id": "creator-1",
                    "avatar_url": "https://p16-common-sign.tiktokcdn-us.com/old.jpg",
                }
            },
        ),
        access_token="secret",
        shop_cipher="secret",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    creator = payloads[0]["creator"]
    assert result.avatar_stored_count == 1
    assert storage.sources == ["https://p16-common-sign.tiktokcdn-us.com/old.jpg"]
    assert creator["avatar_object_key"].endswith("hash.jpg")
    assert "refresh_token" not in repr(creator["performance"])
    assert creator["performance"]["avatar_url"].endswith("/new.jpg")


@pytest.mark.asyncio
async def test_avatar_failure_does_not_discard_performance_enrichment() -> None:
    service = SampleCreatorEnrichmentService(FakeClient(), FakeAvatarStorage(fail=True))
    payloads = [{"creator": {"creator_open_id": "creator-1"}}]

    result = await service.enrich(
        payloads,
        source_payloads=({"creator": {"creator_open_id": "creator-1"}},),
        access_token="secret",
        shop_cipher="secret",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert result.performance_enriched_count == 1
    assert result.avatar_error_count == 1
    assert payloads[0]["creator"]["performance"]["sample_score"] == {"overall": "86"}


@pytest.mark.asyncio
async def test_transport_failure_does_not_discard_sample_application() -> None:
    service = SampleCreatorEnrichmentService(
        FailingPerformanceClient(),
        FakeAvatarStorage(),
    )
    payloads = [{"creator": {"creator_open_id": "creator-1"}}]

    result = await service.enrich(
        payloads,
        source_payloads=({"creator": {"creator_open_id": "creator-1"}},),
        access_token="secret",
        shop_cipher="secret",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        observed_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    assert result.performance_enriched_count == 0
    assert result.performance_error_count == 1
    assert "performance" not in payloads[0]["creator"]


@pytest.mark.asyncio
async def test_enrichment_fetches_duplicate_creator_performance_once() -> None:
    client = CountingPerformanceClient()
    service = SampleCreatorEnrichmentService(client, None, min_interval_seconds=0)
    payloads = [
        {"creator": {"creator_open_id": "creator-1"}},
        {"creator": {"creator_open_id": "creator-1"}},
    ]

    result = await service.enrich(
        payloads,
        source_payloads=tuple(payloads),
        access_token="secret",
        shop_cipher="secret",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert client.creator_ids == ["creator-1"]
    assert result.performance_enriched_count == 2
    assert all("performance" in payload["creator"] for payload in payloads)


@pytest.mark.asyncio
async def test_enrichment_stops_creator_requests_after_rate_limit() -> None:
    client = RateLimitedPerformanceClient()
    service = SampleCreatorEnrichmentService(client, None, min_interval_seconds=0)
    payloads = [
        {"creator": {"creator_open_id": "creator-1"}},
        {"creator": {"creator_open_id": "creator-2"}},
    ]

    result = await service.enrich(
        payloads,
        source_payloads=tuple(payloads),
        access_token="secret",
        shop_cipher="secret",
        tenant_id=uuid4(),
        shop_id=uuid4(),
        observed_at=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert client.calls == 1
    assert result.performance_error_count == 2
