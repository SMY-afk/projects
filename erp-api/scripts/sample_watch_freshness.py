"""Read-only five-shop sample and Affiliate Center freshness preflight."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from scripts.sample_watch_source_conditions import successful_source_conditions

TENANT_ID = UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26")
SHOPS = {
    "local": UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10"),
    "cross-border-3": UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6"),
    "cross-border-4": UUID("50770999-40ce-5b84-bb01-13701932bdf1"),
    "cross-border-7": UUID("fe629cb8-fa7b-56a5-970c-2f6e9ebc5703"),
    "cross-border-12": UUID("5e1fed24-8268-5b5a-9ead-5efb862e7a51"),
}


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _age(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value.astimezone(UTC)).total_seconds()))


async def _latest(session, model, shop_id: UUID, *conditions, order_by):
    statement = (
        select(model)
        .where(model.tenant_id == TENANT_ID, model.shop_id == shop_id, *conditions)
        .order_by(order_by.desc())
        .limit(1)
    )
    return await session.scalar(statement)


def _analytics_sources_complete(
    successful: dict[str, AnalyticsSyncRun | None],
    available: dict[str, date | None],
    timezone: str | None,
) -> bool:
    if not timezone or any(
        not available.get(resource)
        for resource in ("creators", "videos", "liveAccounts")
    ):
        return False
    zone = ZoneInfo(timezone)
    for resource, key in (
        ("affiliate_creator", "creators"),
        ("affiliate_video", "videos"),
    ):
        run = successful.get(resource)
        day = available[key]
        if run is None or day is None:
            return False
        day_start = datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)
        if not run.window_start <= day_start < run.window_end:
            return False
    live = successful.get("live")
    if live is None or live.latest_available_date is None:
        return False
    if live.latest_available_date != available["liveAccounts"]:
        return False
    live_start = datetime.combine(
        available["liveAccounts"], time.min, tzinfo=zone
    ).astimezone(UTC)
    if not live.window_start <= live_start < live.window_end:
        return False
    return (
        all(
            run is not None
            and run.status == "succeeded"
            and run.fetched_count == run.persisted_count
            for run in successful.values()
        )
        and len(successful) == 3
    )


async def _shop_report(
    database: Database,
    repository: AffiliateCenterReadRepository,
    name: str,
    shop_id: UUID,
    now: datetime,
    sample_stale_seconds: int,
) -> dict[str, object]:
    available = await repository.latest_available_dates(TENANT_ID, shop_id)
    async with database.system_session_factory() as session:
        batch = await _latest(
            session, SampleIngestBatch, shop_id, SampleIngestBatch.sample_type == "free",
            order_by=SampleIngestBatch.started_at
        )
        complete_batch = await _latest(
            session,
            SampleIngestBatch,
            shop_id,
            SampleIngestBatch.status == "complete",
            SampleIngestBatch.sample_type == "free",
            order_by=SampleIngestBatch.finished_at,
        )
        source_run = await _latest(
            session,
            SampleSyncRun,
            shop_id,
            SampleSyncRun.sync_type == "source_to_postgres",
            SampleSyncRun.sample_type == "free",
            order_by=SampleSyncRun.started_at,
        )
        source_success = await _latest(
            session,
            SampleSyncRun,
            shop_id,
            SampleSyncRun.sync_type == "source_to_postgres",
            SampleSyncRun.status == "succeeded",
            SampleSyncRun.sample_type == "free",
            order_by=SampleSyncRun.finished_at,
        )
        post_source = await _latest(
            session,
            SampleSyncRun,
            shop_id,
            SampleSyncRun.sync_type == "postgres_to_feishu",
            order_by=SampleSyncRun.started_at,
        )
        creator_report = await _latest(
            session,
            AffiliateCreatorReport,
            shop_id,
            AffiliateCreatorReport.period_end == available.get("creators"),
            order_by=AffiliateCreatorReport.captured_at,
        )
        timezone = await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
        analytics = {}
        successful_analytics = {}
        for resource in ("affiliate_creator", "affiliate_video", "live"):
            analytics[resource] = await _latest(
                session,
                AnalyticsSyncRun,
                shop_id,
                AnalyticsSyncRun.resource_type == resource,
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                order_by=AnalyticsSyncRun.started_at,
            )
            successful_analytics[resource] = await _latest(
                session,
                AnalyticsSyncRun,
                shop_id,
                AnalyticsSyncRun.resource_type == resource,
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                AnalyticsSyncRun.status == "succeeded",
                *successful_source_conditions(resource, available, timezone),
                order_by=AnalyticsSyncRun.finished_at,
            )
    sample_age = _age(now, complete_batch.finished_at if complete_batch else None)
    source_age = _age(now, source_success.finished_at if source_success else None)
    current_batch_acceptable = bool(
        batch
        and (
            (
                batch.status == "complete"
                and batch.finished_at
                and (
                    batch.expected_total is None
                    or batch.expected_total == batch.captured_total
                )
            )
            or (batch.status == "running" and _age(now, batch.started_at) <= 600)
        )
    )
    current_run_acceptable = bool(
        source_run
        and (
            source_run.status == "succeeded"
            or (
                source_run.status == "running"
                and _age(now, source_run.started_at) <= 600
            )
        )
    )
    sample_ok = bool(
        current_batch_acceptable
        and current_run_acceptable
        and sample_age is not None
        and source_age is not None
        and sample_age <= sample_stale_seconds
        and source_age <= sample_stale_seconds
    )
    creator_complete = bool(
        creator_report
        and creator_report.status == "complete"
        and creator_report.completeness_reason == "complete"
        and creator_report.expected_total == creator_report.records_received
    )
    analytics_complete = _analytics_sources_complete(
        successful_analytics, available, timezone
    )
    daily_local_ready = bool(
        creator_complete
        and analytics_complete
        and available.get("creators")
        and available.get("videos")
        and available.get("liveAccounts")
    )
    return {
        "shop": name,
        "sample_ok": sample_ok,
        "sample_batch": {
            "status": batch.status if batch else None,
            "finished_at": _iso(batch.finished_at) if batch else None,
            "expected_total": batch.expected_total if batch else None,
            "captured_total": batch.captured_total if batch else None,
            "last_complete_age_seconds": sample_age,
        },
        "sample_source_run": {
            "status": source_run.status if source_run else None,
            "finished_at": _iso(source_run.finished_at) if source_run else None,
            "last_success_age_seconds": source_age,
        },
        "post_source_status": post_source.status if post_source else None,
        "daily_local_ready": daily_local_ready,
        "available_dates": {key: _iso(value) for key, value in available.items()},
        "creator_report": {
            "status": creator_report.status if creator_report else None,
            "period_end": _iso(creator_report.period_end) if creator_report else None,
            "expected_total": creator_report.expected_total if creator_report else None,
            "records_received": creator_report.records_received
            if creator_report
            else None,
        },
        "analytics": {
            resource: {
                "status": run.status if run else None,
                "latest_available_date": _iso(run.latest_available_date)
                if run
                else None,
                "finished_at": _iso(run.finished_at) if run else None,
                "fetched_count": run.fetched_count if run else None,
                "persisted_count": run.persisted_count if run else None,
            }
            for resource, run in analytics.items()
        },
    }


async def build_report(sample_stale_seconds: int = 900) -> dict[str, object]:
    now = datetime.now(UTC)
    database = Database(get_settings().database_url)
    try:
        repository = AffiliateCenterReadRepository(database)
        shops = [
            await _shop_report(
                database, repository, name, shop_id, now, sample_stale_seconds
            )
            for name, shop_id in SHOPS.items()
        ]
    finally:
        await database.dispose()
    return {
        "checked_at": now.isoformat(),
        "sample_all_ok": all(item["sample_ok"] for item in shops),
        "daily_local_all_ready": all(item["daily_local_ready"] for item in shops),
        "tk_freshness_confirmation_required": True,
        "shops": shops,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-stale-seconds", type=int, default=900)
    parser.add_argument("--require-daily-local-ready", action="store_true")
    args = parser.parse_args()
    if args.sample_stale_seconds < 600:
        parser.error("Sample stale threshold must be at least 600 seconds.")
    report = asyncio.run(build_report(args.sample_stale_seconds))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    if args.require_daily_local_ready and not report["daily_local_all_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
