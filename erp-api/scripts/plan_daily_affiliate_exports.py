"""Print read-only five-shop rolling XLSX gaps for the local capture host."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

from arq.connections import RedisSettings, create_pool
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.affiliate_sample_priority import sample_round_releases_affiliate
from erp_api.services.affiliate_schedule_queries import (
    daily_collection_window_open,
    latest_due_schedule_date,
)
from erp_api.workers.affiliate_live_schedule import _active_live_shops
from scripts.daily_valid_creator_batch import _covered_by_successful_runs
from scripts.daily_valid_creator_report_gate import (
    creator_missing_windows,
    creator_report_windows,
    rolling_windows,
)

RESOURCE_TYPES = {"creators": "affiliate_creator", "videos": "affiliate_video"}
BUSINESS_NAMES = {target.source_name: target.business_name for target in TARGET_SHOPS}


def creator_window_complete(reports, start: date, end: date) -> bool:
    """Require exact adjacent windows without an API-container dependency."""
    step = timedelta(days=1)
    reachable = {end + step}
    for first, last in sorted(reports, reverse=True):
        if start <= first <= last <= end and last + step in reachable:
            reachable.add(first)
    return start in reachable


def missing_windows(
    shop: str, resource: str, cutoff: date, runs: list[dict]
) -> list[dict[str, str]]:
    if resource != "videos":
        raise ValueError("Only per-video windows can reuse overlapping coverage")
    return [
        {"resource": resource, "start": start.isoformat(), "end": end.isoformat()}
        for start, end in rolling_windows(cutoff)
        if not _covered_by_successful_runs(runs, shop, "video", start, end)
    ]


async def successful_runs(database, shop, business_name: str) -> list[dict]:
    async with database.system_session_factory() as session:
        rows = (
            await session.scalars(
                select(AnalyticsSyncRun).where(
                    AnalyticsSyncRun.tenant_id == shop.tenant_id,
                    AnalyticsSyncRun.shop_id == shop.shop_id,
                    AnalyticsSyncRun.resource_type.in_(RESOURCE_TYPES.values()),
                    AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                    AnalyticsSyncRun.status == "succeeded",
                )
            )
        ).all()
    zone = ZoneInfo(shop.timezone)
    return [
        {
            "shop": business_name,
            "resource": next(
                name[:-1] if name == "creators" else "video"
                for name, kind in RESOURCE_TYPES.items()
                if kind == row.resource_type
            ),
            "window": (
                row.window_start.astimezone(zone).date(),
                row.window_end.astimezone(zone).date() - timedelta(days=1),
            ),
            "status": row.status,
            "fetched": row.fetched_count,
            "persisted": row.persisted_count,
        }
        for row in rows
        if row.window_start and row.window_end
    ]


def exact_video_path_missing(
    shop: str, cutoff: date, runs: list[dict], *, start: date | None = None
) -> list[dict]:
    """Minimize new requests, then captured days, without trimming aggregate XLSX."""
    start = start if start is not None else cutoff - relativedelta(months=2)
    after = cutoff + timedelta(days=1)
    available = {
        row["window"] for row in runs
        if row["shop"] == shop and row["resource"] == "video"
        and row["status"] == "succeeded" and row["fetched"] == row["persisted"]
        and start <= row["window"][0] <= row["window"][1] <= cutoff
    }

    @cache
    def visit(current):
        if current == after:
            return (0, 0, 0), ()
        choices = [(end, False) for first, end in available if first == current]
        choices.sort(reverse=True)
        choices.extend((min(current + timedelta(days=days - 1), cutoff), True)
                       for days in range(min(30, (after - current).days), 0, -1))
        best = None
        for end, capture in choices:
            score, remainder = visit(end + timedelta(days=1))
            candidate_score = (
                score[0] + int(capture),
                score[1] + ((end - current).days + 1 if capture else 0),
                score[2] + 1,
            )
            missing = ((current, end), *remainder) if capture else remainder
            candidate = candidate_score, missing
            if best is None or candidate_score < best[0]:
                best = candidate
        return best

    return [{"resource": "videos", "start": str(first), "end": str(last)}
            for first, last in visit(start)[1]]


async def build_plan(database, redis, now: datetime) -> dict:
    settings = get_settings()
    shops = [
        shop for shop in await _active_live_shops(database)
        if shop.tenant_id == settings.affiliate_export_tenant_id
        and shop.source_name in BUSINESS_NAMES
    ]
    if len(shops) != len(TARGET_SHOPS) or {
        shop.source_name for shop in shops
    } != set(BUSINESS_NAMES):
        raise RuntimeError("Exact five authorized ERP shops are unavailable")
    health_repo = AffiliateCaptureHealthRepository(redis)
    result = {
        "generated_at": now.isoformat(),
        "batch_date": latest_due_schedule_date(now).isoformat(),
        "window_open": daily_collection_window_open(now),
        "shops": [],
    }
    for shop in sorted(shops, key=lambda item: item.source_name):
        name = BUSINESS_NAMES[shop.source_name]
        health = await health_repo.get(shop.tenant_id, shop.shop_id)
        ready = health.state == "online" and health.session_available
        released = ready and await sample_round_releases_affiliate(
            database, shop.tenant_id, shop.shop_id, now=now
        )
        evidence = {
            resource: await health_repo.observed_evidence_for(
                shop.tenant_id, shop.shop_id, resource, now=now
            )
            for resource in RESOURCE_TYPES
        }
        runs = await successful_runs(database, shop, name)
        missing = []
        if evidence["creators"] is not None:
            cutoff = evidence["creators"][0]
            reports = await creator_report_windows(database, shop, cutoff)
            missing.extend(creator_missing_windows(cutoff, reports))
            recent_start = cutoff - timedelta(days=6)
            if not creator_window_complete(reports, recent_start, cutoff):
                repair = {
                    "resource": "creators", "start": str(recent_start),
                    "end": str(cutoff),
                }
                if repair not in missing:
                    missing.append(repair)
        if evidence["videos"] is not None:
            cutoff = evidence["videos"][0]
            missing.extend(missing_windows(name, "videos", cutoff, runs))
            for start in (cutoff - relativedelta(months=2), cutoff - timedelta(days=6)):
                for repair in exact_video_path_missing(name, cutoff, runs, start=start):
                    if repair not in missing:
                        missing.append(repair)
        result["shops"].append(
            {
                "business_name": name,
                "source_name": shop.source_name,
                "shop_id": str(shop.shop_id),
                "timezone": shop.timezone,
                "currency": shop.currency,
                "health_ready": ready,
                "sample_released": released,
                "cutoffs": {
                    resource: (
                        {"date": observed[0].isoformat(), "observed_at": observed[1].isoformat()}
                        if observed else None
                    )
                    for resource, observed in evidence.items()
                },
                "missing": missing,
            }
        )
    return result


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        print(json.dumps(await build_plan(database, redis, datetime.now(UTC))))
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
