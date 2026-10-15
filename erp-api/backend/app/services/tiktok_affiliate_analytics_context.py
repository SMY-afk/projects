from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class AffiliateAnalyticsResponseContext:
    platform_shop_id: str | None
    request_id: str | None
    request_url: str | None = None
    request_headers: Mapping[str, str] | None = None
    request_body: Mapping[str, object] | None = None


AffiliateAnalyticsPagePersister = Callable[
    [
        str,
        Mapping[str, object],
        Mapping[str, object],
        AffiliateAnalyticsResponseContext,
        int,
        int | None,
    ],
    Awaitable[None],
]
AffiliateAnalyticsTerminalHandler = Callable[
    [str, Mapping[str, object]], Awaitable[None]
]
