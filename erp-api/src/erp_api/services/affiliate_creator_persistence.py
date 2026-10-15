from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import (
    AffiliateCreator,
    AffiliateCreatorMetric,
    AffiliateCreatorReport,
)
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_avatar_cache_policy import cached_avatar_expression
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO
from erp_api.services.affiliate_creator_persistence_rows import (
    METRIC_FIELDS,
    _batches,
    capture_lock_key,
    creator_row,
    metric_row,
    running_report_run_id,
)


class AffiliateCreatorPersistence:
    """Persist one browser-capture revision and its tenant/shop creator facts."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def begin_capture(
        self,
        tenant_id: UUID,
        query: AffiliateCenterQuery,
        *,
        platform_shop_id: str,
        job_id: str,
        source_kind: str = "page_capture",
        source_metadata: Mapping[str, object] | None = None,
    ) -> tuple[UUID, UUID]:
        if query.resource is not AffiliateCenterResource.CREATORS:
            raise ValueError("Creator capture requires a creator query.")
        if not platform_shop_id or len(platform_shop_id) > 255:
            raise ValueError("platform_shop_id must contain 1 to 255 characters.")
        if not job_id or len(job_id) > 160:
            raise ValueError("job_id must contain 1 to 160 characters.")
        if source_kind not in {"page_capture", "browser_export", "official_api"}:
            raise ValueError("Unsupported creator source kind.")
        window_start, window_end = query.utc_window()
        async for session in self._database.session(tenant_id):
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        capture_lock_key(tenant_id, query.shop_id, query.fingerprint)
                    )
                )
            )
            intent_run = await session.scalar(
                select(AnalyticsSyncRun).where(
                    AnalyticsSyncRun.tenant_id == tenant_id,
                    AnalyticsSyncRun.shop_id == query.shop_id,
                    AnalyticsSyncRun.resource_type == "affiliate_creator",
                    AnalyticsSyncRun.job_id == job_id,
                    AnalyticsSyncRun.status.in_(("queued", "running")),
                )
            )
            if intent_run is None and job_id.startswith(
                ("affiliate-intent:", "affiliate-schedule:")
            ):
                raise RuntimeError("Affiliate creator sync intent is unavailable.")
            running_report = await session.scalar(
                select(AffiliateCreatorReport)
                .where(
                    AffiliateCreatorReport.tenant_id == tenant_id,
                    AffiliateCreatorReport.shop_id == query.shop_id,
                    AffiliateCreatorReport.query_fingerprint == query.fingerprint,
                    AffiliateCreatorReport.source_kind == source_kind,
                    AffiliateCreatorReport.status == "running",
                )
                .order_by(AffiliateCreatorReport.revision_no.desc())
                .limit(1)
            )
            if running_report is not None:
                if (
                    running_report.source_metadata.get("platformShopId")
                    != platform_shop_id
                ):
                    raise RuntimeError(
                        "Running creator report belongs to another platform shop."
                    )
                existing_run_id = running_report_run_id(running_report)
                if intent_run is not None and intent_run.id != existing_run_id:
                    raise RuntimeError(
                        "Another creator capture is active for this query."
                    )
                running_run = await session.scalar(
                    select(AnalyticsSyncRun).where(
                        AnalyticsSyncRun.id == existing_run_id,
                        AnalyticsSyncRun.tenant_id == tenant_id,
                        AnalyticsSyncRun.shop_id == query.shop_id,
                        AnalyticsSyncRun.resource_type == "affiliate_creator",
                        AnalyticsSyncRun.status == "running",
                    )
                )
                if running_run is None:
                    raise RuntimeError(
                        "Running creator report has no active synchronization run."
                    )
                return running_run.id, running_report.id
            report_id = uuid4()
            revision = (
                await session.scalar(
                    select(func.max(AffiliateCreatorReport.revision_no)).where(
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id == query.shop_id,
                        AffiliateCreatorReport.query_fingerprint == query.fingerprint,
                    )
                )
                or 0
            ) + 1
            if intent_run is not None:
                if (
                    intent_run.window_start != window_start
                    or intent_run.window_end != window_end
                    or intent_run.currency != query.currency
                ):
                    raise RuntimeError(
                        "Affiliate creator payload does not match its sync intent."
                    )
                run = intent_run
                if run.status == "queued":
                    run.status = "running"
                    run.attempt_count += 1
                    run.started_at = datetime.now(UTC)
            else:
                run = AnalyticsSyncRun(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    shop_id=query.shop_id,
                    resource_type="affiliate_creator",
                    job_id=job_id,
                    status="running",
                    attempt_count=1,
                    window_start=window_start,
                    window_end=window_end,
                    currency=query.currency,
                    account_type="AFFILIATE_ACCOUNTS",
                    start_cursor=None,
                    recovery_cursor=None,
                    started_at=datetime.now(UTC),
                )
            run_id = run.id
            report = AffiliateCreatorReport(
                id=report_id,
                tenant_id=tenant_id,
                scope_label=platform_shop_id,
                shop_id=query.shop_id,
                period_start=query.window_start,
                period_end=query.window_end,
                window_start_utc=window_start,
                window_end_utc=window_end,
                shop_timezone=query.shop_timezone,
                currency=query.currency,
                source_kind=source_kind,
                source_fingerprint=f"{source_kind.replace('_', '-')}:{run_id}",
                source_metadata={
                    **dict(source_metadata or {}),
                    "platformShopId": platform_shop_id,
                    "syncRunId": str(run_id),
                },
                query_fingerprint=query.fingerprint,
                revision_no=revision,
                status="running",
                filters=dict(query.filters),
            )
            session.add_all([report] if intent_run is not None else [run, report])
            await session.flush()
            await session.commit()
            return run_id, report_id
        raise RuntimeError("Tenant database session was not created.")

    async def persist_page(
        self,
        tenant_id: UUID,
        report_id: UUID,
        page: AffiliateCenterPageDTO,
    ) -> int:
        if page.resource is not AffiliateCenterResource.CREATORS:
            raise ValueError(
                "Affiliate creator persistence requires a creator resource."
            )
        records = list(page.records)
        if any(not isinstance(record, AffiliateCreatorMetricDTO) for record in records):
            raise TypeError("Affiliate creator page contains a non-creator DTO.")
        unique = {record.username_normalized: record for record in records}
        if not unique:
            return 0
        creator_rows = [
            creator_row(tenant_id, page.query.shop_id, record)
            for record in unique.values()
        ]
        async for session in self._database.session(tenant_id):
            creator_ids: dict[str, UUID] = {}
            for batch in _batches(creator_rows):
                creator_insert = insert(AffiliateCreator).values(batch)
                creator_statement = creator_insert.on_conflict_do_update(
                    constraint="uq_affiliate_creators_shop_username",
                    set_={
                        "username": creator_insert.excluded.username,
                        "creator_open_id": func.coalesce(
                            AffiliateCreator.creator_open_id,
                            creator_insert.excluded.creator_open_id,
                        ),
                        "avatar_url": cached_avatar_expression(AffiliateCreator.avatar_url, creator_insert.excluded.avatar_url),
                        "source_identifiers": AffiliateCreator.source_identifiers.op(
                            "||"
                        )(creator_insert.excluded.source_identifiers),
                        "extensions": AffiliateCreator.extensions.op("||")(
                            creator_insert.excluded.extensions
                        ),
                        "last_seen_at": datetime.now(UTC),
                    },
                ).returning(AffiliateCreator.id, AffiliateCreator.username_normalized)
                creator_result = await session.execute(creator_statement)
                creator_ids.update(
                    {row.username_normalized: row.id for row in creator_result}
                )
            if creator_ids.keys() != unique.keys():
                raise RuntimeError("Affiliate creator upsert did not return every ID.")
            metric_rows = [
                metric_row(
                    tenant_id,
                    page.query.shop_id,
                    report_id,
                    creator_ids[key],
                    record,
                )
                for key, record in unique.items()
            ]
            for batch in _batches(metric_rows):
                metric_insert = insert(AffiliateCreatorMetric).values(batch)
                metric_statement = metric_insert.on_conflict_do_update(
                    constraint="uq_affiliate_creator_metrics_shop_report_creator",
                    set_={
                        field: getattr(metric_insert.excluded, field)
                        for field in METRIC_FIELDS
                    },
                )
                await session.execute(metric_statement)
            await session.commit()
            return len(metric_rows)
        raise RuntimeError("Tenant database session was not created.")

    async def refresh_identities(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: list[AffiliateCreatorMetricDTO],
    ) -> int:
        unique = {
            record.username_normalized: record
            for record in records
            if record.avatar_url
        }
        if not unique:
            return 0
        rows = [creator_row(tenant_id, shop_id, record) for record in unique.values()]
        async for session in self._database.session(tenant_id):
            for batch in _batches(rows):
                statement = insert(AffiliateCreator).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_affiliate_creators_shop_username",
                    set_={
                        "username": statement.excluded.username,
                        "creator_open_id": func.coalesce(
                            statement.excluded.creator_open_id,
                            AffiliateCreator.creator_open_id,
                        ),
                        "avatar_url": cached_avatar_expression(AffiliateCreator.avatar_url, statement.excluded.avatar_url),
                        "source_identifiers": AffiliateCreator.source_identifiers.op(
                            "||"
                        )(statement.excluded.source_identifiers),
                        "last_seen_at": datetime.now(UTC),
                    },
                )
                await session.execute(statement)
            await session.commit()
            return len(unique)
        raise RuntimeError("Tenant database session was not created.")
