from collections.abc import AsyncIterator
from dataclasses import replace

from erp_api.services.tiktok_data_client import TikTokLiveAnalyticsClient
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsPage

LIVE_ACCOUNT_TYPES = (
    "OFFICIAL_ACCOUNTS",
    "MARKETING_ACCOUNTS",
    "AFFILIATE_ACCOUNTS",
)


async def iter_classified_live_pages(
    client: TikTokLiveAnalyticsClient,
    access_token: str,
    *,
    shop_cipher: str,
    start_date_ge: str,
    end_date_lt: str,
    page_size: int,
    currency: str,
    account_type: str = "ALL",
) -> AsyncIterator[TikTokAnalyticsPage]:
    """Fetch disjoint LIVE account groups and attach their verified account type."""
    account_types = (
        LIVE_ACCOUNT_TYPES
        if account_type == "ALL"
        else (account_type,)
    )
    if any(value not in LIVE_ACCOUNT_TYPES for value in account_types):
        raise ValueError("Unsupported LIVE account type.")
    for selected_account_type in account_types:
        async for page in client.iter_lives(
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
            page_size=page_size,
            currency=currency,
            account_type=selected_account_type,
        ):
            yield replace(
                page,
                items=[
                    replace(
                        item,
                        fields={**item.fields, "accountType": selected_account_type},
                    )
                    for item in page.items
                ],
            )
