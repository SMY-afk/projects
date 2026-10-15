import asyncio
from datetime import UTC, datetime

from erp_api.services.analytics_live_pages import iter_classified_live_pages
from erp_api.services.tiktok_data_schemas import (
    TikTokAnalyticsItem,
    TikTokAnalyticsPage,
)


class FakeLiveClient:
    def __init__(self) -> None:
        self.calls = []

    async def iter_lives(self, access_token, **kwargs):
        self.calls.append((access_token, kwargs))
        account_type = kwargs["account_type"]
        yield TikTokAnalyticsPage(
            items=[
                TikTokAnalyticsItem(
                    fields={"liveId": f"live-{account_type}"},
                    source_status=None,
                    status=None,
                    source_updated_at=None,
                )
            ],
            next_page_token=None,
            platform_request_id=f"request-{account_type}",
            source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
            raw_payload={"data": {"live_stream_sessions": []}},
        )


def test_live_pages_are_fetched_and_tagged_by_account_type() -> None:
    client = FakeLiveClient()

    async def collect():
        return [
            page
            async for page in iter_classified_live_pages(
                client,
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026-07-17",
                end_date_lt="2026-08-16",
                page_size=100,
                currency="USD",
            )
        ]

    pages = asyncio.run(collect())

    assert [call[1]["account_type"] for call in client.calls] == [
        "OFFICIAL_ACCOUNTS",
        "MARKETING_ACCOUNTS",
        "AFFILIATE_ACCOUNTS",
    ]
    assert [page.items[0].fields["accountType"] for page in pages] == [
        "OFFICIAL_ACCOUNTS",
        "MARKETING_ACCOUNTS",
        "AFFILIATE_ACCOUNTS",
    ]
    assert all(
        page.raw_payload == {"data": {"live_stream_sessions": []}} for page in pages
    )


def test_live_pages_can_fetch_only_affiliate_accounts() -> None:
    client = FakeLiveClient()

    async def collect():
        return [
            page
            async for page in iter_classified_live_pages(
                client,
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026-07-17",
                end_date_lt="2026-08-16",
                page_size=100,
                currency="USD",
                account_type="AFFILIATE_ACCOUNTS",
            )
        ]

    pages = asyncio.run(collect())

    assert [call[1]["account_type"] for call in client.calls] == [
        "AFFILIATE_ACCOUNTS"
    ]
    assert pages[0].items[0].fields["accountType"] == "AFFILIATE_ACCOUNTS"
