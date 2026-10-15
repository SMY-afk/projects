from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID

from app.parsers.affiliate_creator_export_parser import parse_affiliate_creator_export
from erp_api.services import tiktok_transport as transport
from erp_api.services.affiliate_analytics_commit_service import (
    AffiliateAnalyticsCommitService,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import AffiliateSourcePageContext
from erp_api.services.affiliate_center_source_adapters import (
    map_official_creator_page,
    map_official_video_page,
)
from erp_api.services.affiliate_creator_persistence import AffiliateCreatorPersistence
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    AffiliateCreatorReportPartial,
)
from erp_api.services.affiliate_official_creator_validation import (
    validate_official_creator_export,
)
from erp_api.services.affiliate_official_video_payload import (
    latest_available,
    total_count,
)
from erp_api.services.affiliate_source_resolver import AffiliateSourceResolver
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence


class OfficialAffiliateSyncService:
    """Sync official affiliate data without crossing tenant or shop boundaries."""

    def __init__(
        self,
        sync_repository,
        shop_repository,
        source_resolver: AffiliateSourceResolver,
        video_client,
        compass_client,
        creator_persistence: AffiliateCreatorPersistence,
        video_persistence: AffiliateVideoPersistence,
        availability_repository=None,
        compass_rate_gate=None,
    ) -> None:
        self._sync_repository = sync_repository
        self._shop_repository = shop_repository
        self._source_resolver = source_resolver
        self._video_client = video_client
        self._compass_client = compass_client
        self._creator_persistence = creator_persistence
        self._video_persistence = video_persistence
        self._commit = AffiliateAnalyticsCommitService(sync_repository)
        self._availability = availability_repository
        self._compass_rate_gate = compass_rate_gate

    async def sync(
        self,
        tenant_id: UUID,
        query: AffiliateCenterQuery,
        *,
        job_id: str,
    ):
        if await self._source_resolver.source_kind(tenant_id, query.shop_id) != "official_api":
            raise RuntimeError("Official affiliate sync is not enabled for this shop.")
        shop = await self._shop_repository.get_authorized_tiktok_shop(
            tenant_id, query.shop_id
        )
        token = await self._shop_repository.get_access_token(tenant_id, query.shop_id)
        cipher = await self._shop_repository.get_shop_cipher(tenant_id, query.shop_id)
        if shop is None or not token or not cipher:
            raise RuntimeError("Official affiliate sync requires shop credentials.")

        if query.resource is AffiliateCenterResource.CREATORS:
            app_profile = await self._shop_repository.get_app_profile(
                tenant_id, query.shop_id
            )
            if not app_profile:
                raise RuntimeError("Official affiliate sync requires an App profile.")
            if self._compass_rate_gate is not None:
                await self._compass_rate_gate.acquire(app_profile)
            run_id, report_id = await self._start(tenant_id, query, shop, job_id)
            try:
                return await self._sync_creators(
                    tenant_id, query, run_id, report_id, token=token, cipher=cipher
                )
            except (transport.TikTokRateLimitError, transport.TikTokApiError) as error:
                if self._compass_rate_gate is not None and (
                    isinstance(error, transport.TikTokRateLimitError)
                    or error.code == "13017003"
                ):
                    retry_after = getattr(error, "retry_after_seconds", None) or 3_600
                    await self._compass_rate_gate.defer(
                        app_profile,
                        retry_after_seconds=max(3_600, retry_after),
                    )
                raise
        run_id, report_id = await self._start(tenant_id, query, shop, job_id)
        return await self._sync_videos(
            tenant_id, query, run_id, report_id, token=token, cipher=cipher
        )

    async def _sync_creators(
        self, tenant_id, query, run_id, report_id, *, token, cipher
    ):
        try:
            with transport.tiktok_request_context(
                tenant_id=str(tenant_id), shop_id=str(query.shop_id)
            ):
                export = await self._compass_client.export_creators(
                    token,
                    shop_cipher=cipher,
                    window_start=query.window_start,
                    window_end=query.window_end,
                )
            rows = parse_affiliate_creator_export(export.content, query.currency)
            audit = validate_official_creator_export(
                export,
                window_start=query.window_start,
                window_end=query.window_end,
                rows=rows,
            )
            request_id = "compass:" + sha256(export.task_id.encode()).hexdigest()[:32]
            creator_page = map_official_creator_page(
                query,
                rows,
                context=AffiliateSourcePageContext(
                    request_id=request_id,
                    pagination_mode="cursor",
                    page_number=1,
                    page_size=max(1, len(rows)),
                    has_more=False,
                    total_count=len(rows),
                    source_updated_at=datetime.now(UTC),
                ),
                raw_payload={
                    "source": "affiliate_seller_compass_creator_export",
                    "format": "xlsx",
                    "recordCount": len(rows),
                    "fileSha256": audit.file_sha256,
                    "affiliateGmvMinor": audit.gmv_minor,
                    "estimatedCommissionMinor": audit.commission_minor,
                    "affiliateOrderCount": audit.order_count,
                    "affiliateProductItemsSold": audit.items_sold,
                    "taskFingerprint": request_id,
                },
            )
            persisted_count = await self._commit.commit_page(
                tenant_id,
                run_id,
                creator_page,
                lambda page: self._creator_persistence.persist_page(
                    tenant_id, report_id, page
                ),
            )
            count = audit.record_count
            if len(creator_page.records) != count or persisted_count not in {0, count}:
                raise RuntimeError(
                    "Official Creator export did not persist every validated record."
                )
            return await self._commit.complete_creator_report(
                tenant_id,
                run_id,
                report_id,
                AffiliateCreatorReportCompletion(
                    expected_total=count,
                    pages_fetched=1,
                    records_received=count,
                    records_unique=count,
                    duplicate_count=0,
                    completeness_reason="complete",
                ),
            )
        except Exception:
            await self._mark_partial(
                tenant_id,
                AffiliateCenterResource.CREATORS,
                run_id,
                report_id,
                pages=0,
                received=0,
            )
            raise

    async def _sync_videos(
        self, tenant_id, query, run_id, report_id, *, token, cipher
    ):
        page_count = received = 0
        try:
            start = query.window_start.isoformat()
            exclusive_end = date.fromordinal(query.window_end.toordinal() + 1).isoformat()
            with transport.tiktok_request_context(
                tenant_id=str(tenant_id), shop_id=str(query.shop_id)
            ):
                pages = self._video_client.iter_videos(
                    token,
                    shop_cipher=cipher,
                    start_date_ge=start,
                    end_date_lt=exclusive_end,
                    page_size=100,
                    currency=query.currency,
                    account_type="AFFILIATE_ACCOUNTS",
                )
                async for source_page in pages:
                    page_count += 1
                    received += len(source_page.items)
                    latest = latest_available(source_page.raw_payload)
                    if latest is not None and self._availability is not None:
                        await self._availability.set(tenant_id, query.shop_id, latest)
                    if latest is not None and query.window_end > latest:
                        raise ValueError(
                            f"TikTok Affiliate data is available through {latest}."
                        )
                    video_page = map_official_video_page(
                        query,
                        source_page.items,
                        context=AffiliateSourcePageContext(
                            request_id=source_page.platform_request_id
                            or f"official-video:{run_id}:{page_count}",
                            pagination_mode="cursor",
                            page_number=page_count,
                            page_size=100,
                            next_cursor=source_page.next_page_token,
                            has_more=bool(source_page.next_page_token),
                            total_count=total_count(source_page.raw_payload),
                            source_updated_at=source_page.source_updated_at,
                        ),
                        raw_payload=source_page.raw_payload,
                    )
                    await self._commit.commit_page(
                        tenant_id,
                        run_id,
                        video_page,
                        lambda page: self._video_persistence.persist_page(
                            tenant_id, run_id, page
                        ),
                    )
            return await self._commit.complete_video(
                tenant_id, run_id, committed_cursor=None
            )
        except Exception:
            await self._mark_partial(
                tenant_id,
                AffiliateCenterResource.VIDEOS,
                run_id,
                report_id,
                page_count,
                received,
            )
            raise

    async def _start(self, tenant_id, query, shop, job_id):
        if query.resource is AffiliateCenterResource.CREATORS:
            return await self._creator_persistence.begin_capture(
                tenant_id,
                query,
                platform_shop_id=str(shop["platform_shop_id"]),
                job_id=job_id,
                source_kind="official_api",
                source_metadata={"provider": "tiktok_compass_creator_xlsx"},
            )
        start, end = query.utc_window()
        run_id = await self._sync_repository.create_run(
            tenant_id,
            query.shop_id,
            resource_type="affiliate_video",
            window_start=start,
            window_end=end,
            start_cursor=None,
            job_id=job_id,
            currency=query.currency,
            account_type="AFFILIATE_ACCOUNTS",
        )
        await self._sync_repository.start_run(tenant_id, run_id)
        return run_id, None

    async def _mark_partial(self, tenant_id, resource, run_id, report_id, pages, received) -> None:
        if resource is AffiliateCenterResource.CREATORS:
            await self._commit.mark_creator_partial(
                tenant_id,
                run_id,
                report_id,
                AffiliateCreatorReportPartial(
                    expected_total=None,
                    pages_fetched=pages,
                    records_received=received,
                    records_unique=0,
                    duplicate_count=0,
                    completeness_reason="page_failed",
                ),
            )
        else:
            await self._commit.mark_video_partial(tenant_id, run_id, "page_failed")
