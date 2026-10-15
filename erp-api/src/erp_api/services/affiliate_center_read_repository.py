from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import desc, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.shop import Shop
from erp_api.services.affiliate_available_dates_repository import (
    latest_available_dates as read_latest_available_dates,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_read_queries import (
    CreatorSort,
    SortOrder,
    VideoSort,
    latest_failure_run,
    latest_run,
)
from erp_api.services.affiliate_center_summary import (
    empty_creator_summary,
)
from erp_api.services.affiliate_creator_page_query import creator_metric_page
from erp_api.services.affiliate_creator_window_read import aggregated_creator_page
from erp_api.services.affiliate_video_page_query import video_metric_page


class AffiliateCenterReadRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_shop_context(
        self, tenant_id: UUID, shop_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(Shop.timezone, Shop.currency).where(
                        Shop.tenant_id == tenant_id,
                        Shop.id == shop_id,
                        Shop.status == "active",
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            return {"shopTimezone": row.timezone, "currency": row.currency}
        raise RuntimeError("Tenant database session was not created.")

    async def get_shop_context_by_platform_id(
        self, tenant_id: UUID, platform_shop_id: str
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(Shop.id, Shop.timezone, Shop.currency).where(
                        Shop.tenant_id == tenant_id,
                        Shop.platform == "tiktok",
                        Shop.platform_shop_id == platform_shop_id,
                        Shop.status == "active",
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            return {
                "shopId": row.id,
                "shopTimezone": row.timezone,
                "currency": row.currency,
            }
        raise RuntimeError("Tenant database session was not created.")

    async def latest_available_dates(
        self, tenant_id: UUID, shop_id: UUID
    ) -> dict[str, date]:
        return await read_latest_available_dates(self._database, tenant_id, shop_id)

    async def list_creators(
        self,
        tenant_id: UUID,
        query: AffiliateCenterQuery,
        *,
        page: int,
        page_size: int,
        sort: CreatorSort,
        order: SortOrder,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            report = await session.scalar(
                select(AffiliateCreatorReport)
                .where(
                    AffiliateCreatorReport.tenant_id == tenant_id,
                    AffiliateCreatorReport.shop_id == query.shop_id,
                    AffiliateCreatorReport.period_start == query.window_start,
                    AffiliateCreatorReport.period_end == query.window_end,
                    AffiliateCreatorReport.shop_timezone == query.shop_timezone,
                    AffiliateCreatorReport.currency == query.currency,
                    AffiliateCreatorReport.status == "complete",
                )
                .order_by(
                    desc(AffiliateCreatorReport.captured_at),
                    desc(AffiliateCreatorReport.revision_no),
                )
                .limit(1)
            )
            if report is None:
                aggregated = await aggregated_creator_page(
                    session,
                    tenant_id,
                    query,
                    page=page,
                    page_size=page_size,
                    sort=sort,
                    order=order,
                )
                if aggregated is not None:
                    return aggregated
                return _empty_page(
                    page,
                    page_size,
                    sort,
                    order,
                    report=None,
                    summary=empty_creator_summary(),
                )
            return await creator_metric_page(
                session,
                tenant_id,
                query,
                report,
                page=page,
                page_size=page_size,
                sort=sort,
                order=order,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def list_videos(
        self,
        tenant_id: UUID,
        query: AffiliateCenterQuery,
        *,
        page: int,
        page_size: int,
        sort: VideoSort,
        order: SortOrder,
        creator_open_id: str | None,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            return await video_metric_page(
                session,
                tenant_id,
                query,
                page=page,
                page_size=page_size,
                sort=sort,
                order=order,
                creator_open_id=creator_open_id,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def resolve_video_export_window(self, tenant_id: UUID, query):
        from erp_api.services.affiliate_video_window_coverage import (
            resolve_complete_video_window,
        )

        async for session in self._database.session(tenant_id):
            return await resolve_complete_video_window(session, tenant_id, query)
        raise RuntimeError("Tenant database session was not created.")

    async def sync_status(
        self, tenant_id: UUID, shop_id: UUID
    ) -> list[dict[str, object]]:
        items = []
        async for session in self._database.session(tenant_id):
            for resource, resource_type in (
                ("creators", "affiliate_creator"),
                ("videos", "affiliate_video"),
            ):
                run_types = resource_type
                account_type = "AFFILIATE_ACCOUNTS" if resource == "videos" else None
                latest = await session.scalar(
                    latest_run(
                        tenant_id,
                        shop_id,
                        run_types,
                        account_type=account_type,
                    )
                )
                complete = await session.scalar(
                    latest_run(
                        tenant_id,
                        shop_id,
                        run_types,
                        succeeded=True,
                        account_type=account_type,
                    )
                )
                failure = await session.scalar(
                    latest_failure_run(
                        tenant_id,
                        shop_id,
                        run_types,
                        account_type=account_type,
                    )
                )
                if (
                    complete
                    and failure
                    and failure.started_at
                    <= (complete.finished_at or complete.started_at)
                ):
                    failure = None
                items.append(
                    {
                        "resource": resource,
                        "resourceType": resource_type,
                        "status": latest.status if latest else "never_synced",
                        "latestRun": _run_dict(latest) if latest else None,
                        "lastFailureRun": _run_dict(failure) if failure else None,
                        "lastCompleteRunId": complete.id if complete else None,
                        "lastCompleteAt": complete.finished_at if complete else None,
                    }
                )
            return items
        raise RuntimeError("Tenant database session was not created.")


def _run_dict(run) -> dict[str, object]:
    return {
        "runId": run.id,
        "sourceKind": (
            "official_api"
            if run.resource_type == "video"
            or str(run.job_id).startswith("official-affiliate")
            else "page_capture"
        ),
        "status": run.status,
        "fetchedCount": run.fetched_count,
        "persistedCount": run.persisted_count,
        "startedAt": run.started_at,
        "finishedAt": run.finished_at,
        "freshAt": run.last_source_updated_at,
        "errorCategory": run.error_category,
        "errorSummary": run.error_summary,
    }


def _empty_page(page, page_size, sort, order, **snapshot):
    return {
        **snapshot,
        "items": [],
        "page": page,
        "pageSize": page_size,
        "total": 0,
        "sort": sort,
        "order": order,
    }
