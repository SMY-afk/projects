from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import desc, select

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_schedule_coordination import (
    TARGET_AFFILIATE_SHOP_NAMES,
    AvailabilityProvider,
    resolve_shop_cutoffs,
)
from erp_api.services.affiliate_schedule_queries import (
    ScheduledShop,
    daily_collection_window_open,
    latest_due_schedule_date,
    scheduled_affiliate_queries,
    scheduled_query_job_base,
)
from erp_api.services.affiliate_source_resolver import (
    is_official_affiliate_connection,
)

TERMINAL_FAILURES = frozenset({"partial", "failed", "dead_letter"})


ScheduleEnqueuer = Callable[
    [ScheduledShop, AffiliateCenterQuery, str, int], Awaitable[bool]
]
RecoveryProvider = Callable[[UUID, UUID], Awaitable[datetime | None]]


class AffiliateScheduleService:
    def __init__(
        self,
        database,
        *,
        resource: AffiliateCenterResource,
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(minutes=10),
        enqueuer: ScheduleEnqueuer | None = None,
        recovery_provider: RecoveryProvider | None = None,
        availability_provider: AvailabilityProvider | None = None,
    ) -> None:
        self._database = database
        self._repository = AffiliateCaptureIntentRepository(database)
        self._resource = resource
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        self._enqueuer = enqueuer
        self._recovery_provider = recovery_provider
        self._availability_provider = availability_provider

    async def enqueue_due(self, now: datetime) -> int:
        now = _utc(now)
        if not daily_collection_window_open(now):
            return 0
        shops = await self._active_shops()
        shop_cutoffs = await resolve_shop_cutoffs(
            shops,
            self._resource,
            now,
            self._availability_provider,
        )
        batch_date = latest_due_schedule_date(now)
        queued = 0
        for shop in shops:
            latest_available = shop_cutoffs.get(shop.shop_id)
            if latest_available is None:
                continue
            for query in scheduled_affiliate_queries(
                shop, latest_available, self._resource
            ):
                job_base = scheduled_query_job_base(query, batch_date, latest_available)
                attempt = await self._next_attempt(shop, query, job_base, now)
                if attempt is None:
                    continue
                if self._enqueuer is not None:
                    queued += int(await self._enqueuer(shop, query, job_base, attempt))
                    continue
                receipt = (
                    await self._repository.enqueue(
                        shop.tenant_id,
                        [query],
                        job_id_prefix=f"{job_base}:a{attempt}",
                    )
                )[0]
                queued += int(not receipt.existing)
        return queued

    async def _active_shops(self) -> list[ScheduledShop]:
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        Shop.tenant_id,
                        Shop.id,
                        Shop.timezone,
                        Shop.currency,
                        Shop.shop_name,
                        ShopConnection.app_profile,
                        ShopConnection.auth_status,
                        ShopConnection.scopes,
                    )
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                        Shop.timezone.is_not(None),
                    )
                )
            ).all()
            shops = []
            for (
                tenant_id,
                shop_id,
                timezone,
                currency,
                shop_name,
                app_profile,
                auth_status,
                scopes,
            ) in rows:
                if shop_name not in TARGET_AFFILIATE_SHOP_NAMES:
                    continue
                if is_official_affiliate_connection(
                    {
                        "appProfile": app_profile,
                        "status": auth_status,
                        "scopes": scopes or [],
                        "shopName": shop_name,
                    }
                ):
                    continue
                resolved_currency = await _currency(
                    session, tenant_id, shop_id, currency
                )
                shops.append(
                    ScheduledShop(
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        timezone=timezone,
                        currency=resolved_currency,
                        source_name=shop_name,
                    )
                )
            return shops

    async def _next_attempt(
        self,
        shop: ScheduledShop,
        query: AffiliateCenterQuery,
        job_base: str,
        now: datetime,
    ) -> int | None:
        window_start, window_end = query.utc_window()
        resource_type = f"affiliate_{self._resource.value.removesuffix('s')}"
        async with self._database.system_session_factory() as session:
            exact_runs = (
                await session.scalars(
                    select(AnalyticsSyncRun).where(
                        AnalyticsSyncRun.tenant_id == shop.tenant_id,
                        AnalyticsSyncRun.shop_id == shop.shop_id,
                        AnalyticsSyncRun.resource_type == resource_type,
                        AnalyticsSyncRun.window_start == window_start,
                        AnalyticsSyncRun.window_end == window_end,
                        AnalyticsSyncRun.currency == query.currency,
                        AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                    )
                )
            ).all()
            scheduled = (
                await session.scalars(
                    select(AnalyticsSyncRun)
                    .where(
                        AnalyticsSyncRun.tenant_id == shop.tenant_id,
                        AnalyticsSyncRun.shop_id == shop.shop_id,
                        AnalyticsSyncRun.job_id.like(f"{job_base}:%"),
                    )
                    .order_by(desc(AnalyticsSyncRun.started_at))
                )
            ).all()
        recovered_at = (
            await self._recovery_provider(shop.tenant_id, shop.shop_id)
            if self._recovery_provider is not None
            else None
        )
        return next_scheduled_attempt(
            exact_runs,
            scheduled,
            now=now,
            max_attempts=self._max_attempts,
            retry_delay=self._retry_delay,
            recovered_at=recovered_at,
        )


class AffiliateCreatorScheduleService(AffiliateScheduleService):
    def __init__(
        self,
        database,
        *,
        max_attempts: int = 3,
        retry_delay: timedelta = timedelta(minutes=10),
        enqueuer: ScheduleEnqueuer | None = None,
        recovery_provider: RecoveryProvider | None = None,
        availability_provider: AvailabilityProvider | None = None,
    ) -> None:
        super().__init__(
            database,
            resource=AffiliateCenterResource.CREATORS,
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            enqueuer=enqueuer,
            recovery_provider=recovery_provider,
            availability_provider=availability_provider,
        )


def next_scheduled_attempt(
    exact_runs,
    scheduled_runs,
    *,
    now: datetime,
    max_attempts: int,
    retry_delay: timedelta,
    recovered_at: datetime | None = None,
) -> int | None:
    if any(run.status == "succeeded" for run in exact_runs):
        return None
    if any(run.status in {"queued", "running"} for run in exact_runs):
        return None
    if any(run.status == "succeeded" for run in scheduled_runs):
        return None
    if any(run.status in {"queued", "running"} for run in scheduled_runs):
        return None
    failures = [run for run in scheduled_runs if run.status in TERMINAL_FAILURES]
    if not failures:
        return 1
    if len(failures) >= max_attempts:
        if recovered_at is None:
            return None
        latest_failure = failures[0].finished_at or failures[0].started_at
        if _utc(latest_failure) >= _utc(recovered_at):
            return None
    last_finished = failures[0].finished_at or failures[0].started_at
    if _utc(last_finished) + retry_delay > _utc(now):
        return None
    return len(failures) + 1


async def _currency(session, tenant_id: UUID, shop_id: UUID, value: str | None) -> str:
    if value and len(value.strip()) == 3:
        return value.strip().upper()
    latest = await session.scalar(
        select(AffiliateCreatorReport.currency)
        .where(
            AffiliateCreatorReport.tenant_id == tenant_id,
            AffiliateCreatorReport.shop_id == shop_id,
            AffiliateCreatorReport.status == "complete",
        )
        .order_by(desc(AffiliateCreatorReport.captured_at))
        .limit(1)
    )
    return latest or "USD"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Affiliate schedule clock must include a UTC offset.")
    return value.astimezone(UTC)
