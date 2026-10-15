from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from erp_api.services.analytics_live_pages import iter_classified_live_pages
from erp_api.services.analytics_overview import build_overview_snapshots
from erp_api.services.analytics_page_persistence import persist_analytics_page
from erp_api.services.analytics_quality_repository import AnalyticsQualityRepository
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.analytics_resource_types import AnalyticsContentResourceType
from erp_api.services.analytics_sync_repository import (
    AnalyticsSyncRepository,
)
from erp_api.services.analytics_sync_types import AnalyticsSyncResult
from erp_api.services.analytics_sync_windows import (
    AnalyticsSyncWindowError,
    failure_state,
    platform_dates,
    resolve_explicit_window,
    resolve_incremental_window,
)
from erp_api.services.tiktok_data_client import (
    TikTokLiveAnalyticsClient,
    TikTokVideoAnalyticsClient,
)
from erp_api.services.tiktok_data_schemas import classify_analytics_failure
from erp_api.services.tiktok_overview_client import HttpTikTokOverviewClient
from erp_api.services.tiktok_transport import TikTokClientError, tiktok_request_context
from erp_api.services.video_performance_repository import VideoPerformanceRepository

logger = logging.getLogger("erp_api.analytics_sync")


class AnalyticsSyncService:
    """Persists page data while keeping platform pagination inside each ARQ run."""

    def __init__(
        self,
        sync_repository: AnalyticsSyncRepository,
        analytics_repository: AnalyticsRepository,
        video_performance_repository: VideoPerformanceRepository,
        quality_repository: AnalyticsQualityRepository,
        shop_repository,
        client: TikTokVideoAnalyticsClient | TikTokLiveAnalyticsClient,
        overview_client: HttpTikTokOverviewClient,
        *,
        video_external_id_field: str,
        live_external_id_field: str,
        video_amount_currency_pairs: Mapping[str, str],
        live_amount_currency_pairs: Mapping[str, str],
        initial_sync_days: int = 30,
        schedule_mode: Literal["hourly", "daily"] = "daily",
    ) -> None:
        if not 1 <= initial_sync_days <= 30:
            raise ValueError("initial_sync_days must be between 1 and 30.")
        self._sync_repository = sync_repository
        self._analytics_repository = analytics_repository
        self._video_performance_repository = video_performance_repository
        self._quality_repository = quality_repository
        self._shop_repository = shop_repository
        self._client = client
        self._overview_client = overview_client
        self._video_external_id_field = video_external_id_field
        self._live_external_id_field = live_external_id_field
        self._video_amount_currency_pairs = dict(video_amount_currency_pairs)
        self._live_amount_currency_pairs = dict(live_amount_currency_pairs)
        self._initial_sync_days = initial_sync_days
        self._schedule_mode = schedule_mode

    async def sync(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        resource_type: AnalyticsContentResourceType,
        job_id: str,
        attempt: int,
        max_attempts: int,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        currency: str = "USD",
        account_type: str = "ALL",
    ) -> AnalyticsSyncResult | None:
        access_token, shop_cipher, shop_timezone = await self._credentials(
            tenant_id, shop_id
        )
        if (window_start is None) != (window_end is None):
            raise AnalyticsSyncWindowError(
                "Explicit analytics windows require both window_start and window_end."
            )
        explicit_window = window_start is not None
        committed_cursor = None
        if window_start is not None and window_end is not None:
            window = resolve_explicit_window(
                window_start,
                window_end,
                shop_timezone,
            )
        else:
            cursor = await self._sync_repository.get_cursor(
                tenant_id, shop_id, resource_type
            )
            committed_cursor = cursor.committed_cursor
            window = resolve_incremental_window(
                committed_cursor,
                shop_timezone,
                schedule_mode=self._schedule_mode,
                initial_sync_days=self._initial_sync_days,
            )
        if window is None:
            return None
        start, end = window[:2]
        platform_start, platform_end = platform_dates(
            start,
            end,
            shop_timezone,
            explicit_window=explicit_window,
            schedule_mode=self._schedule_mode,
        )
        run_id = await self._sync_repository.create_run(
            tenant_id,
            shop_id,
            resource_type=resource_type,
            window_start=start,
            window_end=end,
            start_cursor=committed_cursor,
            job_id=job_id,
            currency=currency,
            account_type=account_type,
        )
        await self._sync_repository.start_run(tenant_id, run_id)
        try:
            with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop_id)):
                latest_available_date = await self._sync_overview(
                    tenant_id,
                    shop_id,
                    run_id,
                    resource_type=resource_type,
                    access_token=access_token,
                    shop_cipher=shop_cipher,
                    shop_timezone=shop_timezone,
                    start_date=platform_start.isoformat(),
                    end_date=platform_end.isoformat(),
                    currency=currency,
                    account_type=account_type,
                )
                if (
                    explicit_window
                    and resource_type == "video"
                    and latest_available_date is not None
                    and latest_available_date < platform_start
                ):
                    return await self._sync_repository.complete_run(
                        tenant_id,
                        run_id,
                        committed_cursor=None,
                        update_cursor=False,
                    )
                if resource_type == "video":
                    pages = self._client.iter_videos(
                        access_token,
                        shop_cipher=shop_cipher,
                        start_date_ge=platform_start.isoformat(),
                        end_date_lt=platform_end.isoformat(),
                        page_size=100,
                        currency=currency,
                        account_type=account_type,
                    )
                else:
                    pages = iter_classified_live_pages(
                        self._client,
                        access_token,
                        shop_cipher=shop_cipher,
                        start_date_ge=platform_start.isoformat(),
                        end_date_lt=platform_end.isoformat(),
                        page_size=100,
                        currency="USD",
                        account_type=account_type,
                    )
                async for page in pages:
                    items = [
                        replace(
                            item,
                            source_updated_at=item.source_updated_at
                            or page.source_updated_at,
                        )
                        for item in page.items
                    ]
                    await self._quality_repository.record_page_alerts(
                        tenant_id,
                        shop_id,
                        run_id,
                        resource_type=resource_type,
                        items=items,
                        external_id_field=self._external_id_field(resource_type),
                        amount_currency_pairs=self._amount_currency_pairs(
                            resource_type
                        ),
                    )
                    persisted = await persist_analytics_page(
                        self._analytics_repository,
                        self._video_performance_repository,
                        tenant_id,
                        shop_id,
                        run_id,
                        resource_type,
                        items,
                        page.platform_request_id,
                        window_start=start,
                        window_end=end,
                        currency=currency,
                        account_type=account_type,
                        video_external_id_field=self._video_external_id_field,
                        live_external_id_field=self._live_external_id_field,
                    )
                    await self._sync_repository.record_page(
                        tenant_id,
                        run_id,
                        next_cursor=page.next_page_token,
                        fetched_count=len(page.items),
                        persisted_count=persisted,
                        platform_request_id=page.platform_request_id,
                        source_updated_at=page.source_updated_at,
                        raw_payload_kind=f"{resource_type}_page",
                        raw_payload=page.raw_payload,
                    )
            return await self._sync_repository.complete_run(
                tenant_id,
                run_id,
                committed_cursor=end.isoformat() if not explicit_window else None,
                update_cursor=not explicit_window,
            )
        except TikTokClientError as error:
            category = classify_analytics_failure(error).category
            return await self._sync_repository.fail_run(
                tenant_id,
                run_id,
                category=category,
                status=failure_state(category, attempt, max_attempts),
            )
        except Exception:
            logger.exception(
                "analytics_sync_failed",
                extra={
                    "event": "analytics_sync_failed",
                    "tenant_id": str(tenant_id),
                    "shop_id": str(shop_id),
                    "resource_type": resource_type,
                    "run_id": str(run_id),
                },
            )
            return await self._sync_repository.fail_run(
                tenant_id,
                run_id,
                category="platform_error",
                status="failed",
            )

    async def _sync_overview(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        run_id: UUID,
        *,
        resource_type: AnalyticsContentResourceType,
        access_token: str,
        shop_cipher: str,
        shop_timezone: ZoneInfo,
        start_date: str,
        end_date: str,
        currency: str,
        account_type: str,
    ) -> date | None:
        result = await self._overview_client.get_overview(
            resource_type,
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date,
            end_date_lt=end_date,
            currency=currency,
            account_type=account_type,
        )
        await self._sync_repository.record_page(
            tenant_id,
            run_id,
            next_cursor=None,
            fetched_count=0,
            persisted_count=0,
            platform_request_id=result.platform_request_id,
            source_updated_at=None,
            raw_payload_kind=f"{resource_type}_overview",
            raw_payload=result.raw_payload,
            latest_available_date=result.latest_available_date,
        )
        if (
            result.latest_available_date is not None
            and result.latest_available_date < date.fromisoformat(start_date)
        ):
            return result.latest_available_date
        snapshots = build_overview_snapshots(
            resource_type,
            result.intervals,
            shop_timezone,
            platform_request_id=result.platform_request_id,
        )
        await self._analytics_repository.upsert_snapshots(tenant_id, shop_id, snapshots)
        return result.latest_available_date

    async def _credentials(
        self, tenant_id: UUID, shop_id: UUID
    ) -> tuple[str, str, ZoneInfo]:
        shop = await self._shop_repository.get_authorized_tiktok_shop(
            tenant_id, shop_id
        )
        access_token = await self._shop_repository.get_access_token(tenant_id, shop_id)
        shop_cipher = await self._shop_repository.get_shop_cipher(tenant_id, shop_id)
        if shop is None or not access_token or not shop_cipher:
            raise RuntimeError("No authorized TikTok shop credentials are available.")
        timezone_name = shop.get("timezone")
        if not isinstance(timezone_name, str):
            raise AnalyticsSyncWindowError(
                "Analytics shop requires a configured IANA timezone."
            )
        try:
            shop_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise AnalyticsSyncWindowError(
                "Analytics shop has an invalid IANA timezone."
            ) from error
        return access_token, shop_cipher, shop_timezone

    def _external_id_field(self, resource_type: AnalyticsContentResourceType) -> str:
        return (
            self._video_external_id_field
            if resource_type == "video"
            else self._live_external_id_field
        )

    def _amount_currency_pairs(
        self, resource_type: AnalyticsContentResourceType
    ) -> Mapping[str, str]:
        return (
            self._video_amount_currency_pairs
            if resource_type == "video"
            else self._live_amount_currency_pairs
        )
