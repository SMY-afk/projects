from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
    parse_sample_application_page,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)

SAMPLE_APPLICATION_SEARCH_PATH = "/affiliate_seller/202508/sample_applications/search"
CREATOR_PERFORMANCE_PATH = "/affiliate_seller/202508/marketplace_creators/{creator_id}"
CREATOR_PERFORMANCE_FIELDS = frozenset(
    {
        "avg_ec_video_play_count",
        "avg_commission_rate",
        "avg_gmv_per_buyer",
        "avg_ec_live_play_count",
        "avatar",
        "bio_description",
        "brand_collaboration_count",
        "category_gmv_distribution",
        "category_ids",
        "content_gmv_distribution",
        "creator_categories",
        "ec_live_count",
        "ec_live_engagement_rate",
        "ec_video_count",
        "ec_video_engagement_rate",
        "follower_age_distribution",
        "follower_demographics",
        "follower_gender_distribution",
        "follower_region_distribution",
        "gmv",
        "gpm",
        "live_gmv",
        "live_gpm",
        "nickname",
        "post_rate",
        "pps",
        "pps_band",
        "pps_description",
        "promoted_product_num",
        "rating",
        "rating_count",
        "sample_score",
        "sales_window",
        "selection_region",
        "top_collaborated_brand_ids",
        "trends",
        "units_sold",
        "username",
        "video_gmv",
        "video_gpm",
        "video_scope",
        "video_window",
        "live_scope",
        "live_window",
        "audience_window",
    }
)


@dataclass(frozen=True)
class TikTokCreatorPerformance:
    fields: dict[str, object]
    platform_request_id: str | None
    cache_hit: bool


class TikTokSampleApplicationClient(Protocol):
    async def search_page(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
        page_token: str | None = None,
        page_size: int = 50,
        status: str | None = None,
    ) -> TikTokSampleApplicationPage: ...

    def iter_pages(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
        page_size: int = 50,
        status: str | None = None,
    ) -> AsyncIterator[TikTokSampleApplicationPage]: ...

    async def get_creator_performance(
        self,
        access_token: str,
        *,
        creator_open_id: str,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
    ) -> TikTokCreatorPerformance: ...


class HttpTikTokSampleApplicationClient:
    def __init__(
        self,
        transport: TikTokTransport,
        *,
        search_path: str = SAMPLE_APPLICATION_SEARCH_PATH,
        performance_cache_seconds: float = 240,
    ) -> None:
        self._transport = transport
        self._search_path = search_path
        self._performance_cache_seconds = performance_cache_seconds
        self._performance_cache: dict[
            tuple[str, str], tuple[float, dict[str, object]]
        ] = {}

    async def get_creator_performance(
        self,
        access_token: str,
        *,
        creator_open_id: str,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
    ) -> TikTokCreatorPerformance:
        if not creator_open_id:
            raise ValueError("creator_open_id cannot be blank.")
        key = (shop_id, creator_open_id)
        cached = self._performance_cache.get(key)
        now = monotonic()
        if cached is not None and cached[0] > now:
            return TikTokCreatorPerformance(dict(cached[1]), None, True)
        response = await self._transport.request_with_metadata(
            TikTokRequest(
                method="GET",
                path=CREATOR_PERFORMANCE_PATH.format(creator_id=creator_open_id),
                query={"shop_cipher": shop_cipher},
                retryable=True,
            ),
            access_token=access_token,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )
        data = response.payload.get("data")
        creator = data.get("creator") if isinstance(data, dict) else None
        if not isinstance(creator, dict):
            raise TikTokApiError(
                "TikTok creator performance response is invalid.",
                code="invalid_response",
                status_code=502,
                request_id=response.platform_request_id,
            )
        performance = {
            field: creator[field]
            for field in CREATOR_PERFORMANCE_FIELDS
            if field in creator
        }
        self._performance_cache[key] = (
            now + self._performance_cache_seconds,
            performance,
        )
        return TikTokCreatorPerformance(
            dict(performance), response.platform_request_id, False
        )

    async def search_page(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
        page_token: str | None = None,
        page_size: int = 50,
        status: str | None = None,
    ) -> TikTokSampleApplicationPage:
        if not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50.")
        query = {
            "shop_cipher": shop_cipher,
            "page_size": str(page_size),
            **({"page_token": page_token} if page_token else {}),
        }
        body = {"status": status} if status else {}
        response = await self._transport.request_with_metadata(
            TikTokRequest(
                method="POST",
                path=self._search_path,
                query=query,
                json_body=body,
                retryable=True,
            ),
            access_token=access_token,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )
        return parse_sample_application_page(response)

    async def iter_pages(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        tenant_id: str,
        shop_id: str,
        page_size: int = 50,
        status: str | None = None,
    ) -> AsyncIterator[TikTokSampleApplicationPage]:
        current_token: str | None = None
        seen_tokens: set[str] = set()
        expected_total: int | None = None
        captured_total = 0
        while True:
            page = await self.search_page(
                access_token,
                shop_cipher=shop_cipher,
                tenant_id=tenant_id,
                shop_id=shop_id,
                page_token=current_token,
                page_size=page_size,
                status=status,
            )
            if expected_total is None:
                expected_total = page.total_count
            elif page.total_count is not None and page.total_count != expected_total:
                raise TikTokApiError(
                    "TikTok sample pagination changed total_count between pages.",
                    code="pagination_inconsistent_total",
                    status_code=502,
                    request_id=page.platform_request_id,
                )
            captured_total += len(page.applications)
            if expected_total is not None and captured_total > expected_total:
                raise TikTokApiError(
                    "TikTok sample pagination exceeded total_count.",
                    code="pagination_inconsistent_total",
                    status_code=502,
                    request_id=page.platform_request_id,
                )
            yield page
            next_token = page.next_page_token
            if not next_token:
                if expected_total is not None and captured_total != expected_total:
                    raise TikTokApiError(
                        "TikTok sample pagination ended before total_count.",
                        code="pagination_incomplete",
                        status_code=502,
                        request_id=page.platform_request_id,
                    )
                return
            if next_token == current_token or next_token in seen_tokens:
                raise TikTokApiError(
                    "TikTok sample pagination returned a repeated page token.",
                    code="pagination_loop",
                    status_code=502,
                    request_id=page.platform_request_id,
                )
            seen_tokens.add(next_token)
            current_token = next_token
