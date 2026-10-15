"""Read-only gate for the exact five-shop daily affiliate capture batch."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from sqlalchemy import or_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.workers.affiliate_live_schedule import live_windows
from scripts.daily_affiliate_batch_status import task_row
from scripts.daily_valid_creator_core import SHOP_LINES
from scripts.daily_valid_creator_dates import ShopCutoffs

SOURCE_NAMES = {target.source_name: target.business_name for target in TARGET_SHOPS}
RESOURCE_TYPES = {
    "creator": "affiliate_creator",
    "video": "affiliate_video",
    "live": "live",
}


def expected_windows(cutoffs: ShopCutoffs) -> set[tuple[str, str, date, date]]:
    expected = set()
    for shop, ends in cutoffs.items():
        for resource, cutoff_key in (("creator", "creators"), ("video", "videos")):
            end = ends[cutoff_key]
            start = end - relativedelta(months=2)
            cursor = start
            while cursor <= end:
                chunk_end = min(cursor + timedelta(days=29), end)
                expected.add((shop, resource, cursor, chunk_end))
                cursor = chunk_end + timedelta(days=1)
        for start, end in live_windows(ends["liveAccounts"]):
            expected.add((shop, "live", start, end))
    if set(cutoffs) != set(SHOP_LINES):
        raise ValueError("Batch is missing one or more required shops")
    return expected


def evaluate_batch(cutoffs: ShopCutoffs, batch_date: date, runs: list[dict]) -> dict:
    expected = expected_windows(cutoffs)
    grouped: dict[tuple[str, str, date, date], list[dict]] = {}
    errors = []
    for run in runs:
        key = (run["shop"], run["resource"], *run["window"])
        if run["shop"] not in cutoffs or run["resource"] not in RESOURCE_TYPES:
            continue
        cutoff_key = {
            "creator": "creators",
            "video": "videos",
            "live": "liveAccounts",
        }[run["resource"]]
        cutoff = cutoffs[run["shop"]][cutoff_key]
        if (
            run["batch"] == batch_date
            and run["cutoff"] == cutoff
            and key not in expected
        ):
            errors.append(
                f"{run['shop']}.{run['resource']}: unexpected current-batch window"
            )
        if key in expected:
            grouped.setdefault(key, []).append(run)
    reused = 0
    for shop, resource, start, end in sorted(expected):
        label = f"{shop}.{resource} {start}..{end}"
        matching = grouped.get((shop, resource, start, end), [])
        current = [run for run in matching if run["batch"] == batch_date]
        cutoff = cutoffs[shop][
            {"creator": "creators", "video": "videos", "live": "liveAccounts"}[resource]
        ]
        wrong_cutoff = [run for run in current if run["cutoff"] != cutoff]
        if wrong_cutoff:
            errors.append(f"{label}: current-batch cutoff differs from direct TK date")
            continue
        successful = [
            run
            for run in matching
            if run["status"] == "succeeded"
            and isinstance(run["fetched"], int)
            and run["fetched"] >= 0
            and run["fetched"] == run["persisted"]
        ]
        latest_success = max(
            successful,
            key=lambda run: run["finished_at"] or datetime.min.replace(tzinfo=UTC),
            default=None,
        )
        complete_coverage = _covered_by_successful_runs(
            runs, shop, resource, start, end
        )
        passive_intent = bool(
            complete_coverage and current
            and all(run["status"] == "queued" for run in current)
        )
        pending = [
            run
            for run in current
            if run["status"] in {"queued", "running", "retry_wait"}
            and not (passive_intent and run["status"] == "queued")
            and (
                latest_success is None
                or run["started_at"]
                > (latest_success["finished_at"] or latest_success["started_at"])
            )
        ]
        current_success = any(run in successful for run in current)
        current_superseded = passive_intent or (
            latest_success is not None and all(
                run["started_at"] < latest_success["started_at"] for run in current
            )
        )
        if pending:
            errors.append(f"{label}: current-batch task pending")
        if current and not current_success and not current_superseded:
            errors.append(f"{label}: current-batch task did not succeed")
        if current_success and any(
            run["status"] != "succeeded"
            and run["started_at"]
            > (latest_success["finished_at"] or latest_success["started_at"])
            for run in current
        ):
            errors.append(f"{label}: newer current-batch task did not succeed")
        covered = latest_success is None and complete_coverage
        if latest_success is None and not covered:
            errors.append(f"{label}: no complete successful capture")
        elif covered or (latest_success and latest_success["batch"] != batch_date):
            reused += 1
        if not current_superseded and any(
            run["status"] == "succeeded" and run["fetched"] != run["persisted"]
            for run in current
        ):
            errors.append(f"{label}: fetched/persisted totals differ")
    if errors:
        raise ValueError("Batch gate failed: " + "; ".join(sorted(set(errors))))
    return {
        "batch_date": batch_date.isoformat(),
        "required_windows": len(expected),
        "reused_windows": reused,
    }


def _covered_by_successful_runs(
    runs: list[dict], shop: str, resource: str, start: date, end: date
) -> bool:
    intervals = sorted(
        (
            max(start, run["window"][0]),
            min(end, run["window"][1]),
        )
        for run in runs
        if run["shop"] == shop
        and run["resource"] == resource
        and run["status"] == "succeeded"
        and isinstance(run["fetched"], int)
        and run["fetched"] >= 0
        and run["fetched"] == run["persisted"]
        and run["window"][0] <= end
        and run["window"][1] >= start
    )
    cursor = start
    for interval_start, interval_end in intervals:
        if interval_start > cursor:
            return False
        cursor = max(cursor, interval_end + timedelta(days=1))
        if cursor > end:
            return True
    return False


def _query_utc_bounds(earliest: date, latest: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(earliest, datetime.min.time(), UTC),
        datetime.combine(latest + timedelta(days=1), datetime.min.time(), UTC),
    )


async def load_batch_runs(cutoffs: ShopCutoffs, batch_date: date) -> list[dict]:
    settings = get_settings()
    tenant_id = settings.affiliate_export_tenant_id
    if tenant_id is None:
        raise RuntimeError("Affiliate export tenant is not configured")
    expected = expected_windows(cutoffs)
    earliest = min(start for _, _, start, _ in expected)
    latest = max(end for _, _, _, end in expected)
    earliest_utc, latest_utc = _query_utc_bounds(earliest, latest)
    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(AnalyticsSyncRun, Shop.shop_name, Shop.timezone)
                    .join(
                        Shop,
                        (Shop.id == AnalyticsSyncRun.shop_id)
                        & (Shop.tenant_id == AnalyticsSyncRun.tenant_id),
                    )
                    .where(
                        AnalyticsSyncRun.tenant_id == tenant_id,
                        Shop.shop_name.in_(SOURCE_NAMES),
                        AnalyticsSyncRun.resource_type.in_(RESOURCE_TYPES.values()),
                        or_(
                            AnalyticsSyncRun.job_id.like(
                                f"affiliate-schedule:{batch_date:%Y%m%d}:%"
                            ),
                            AnalyticsSyncRun.job_id.like(
                                f"affiliate:live-batch:{batch_date:%Y%m%d}:%"
                            ),
                            (AnalyticsSyncRun.status == "succeeded")
                            & (
                                AnalyticsSyncRun.window_end
                                >= earliest_utc
                            )
                            & (
                                AnalyticsSyncRun.window_start
                                <= latest_utc
                            ),
                        ),
                    )
                )
            ).all()
    finally:
        await database.dispose()
    result = []
    for run, source_name, timezone in rows:
        if not timezone:
            continue
        batch = _job_batch_date(run.job_id)
        if batch == batch_date:
            if run.account_type != "AFFILIATE_ACCOUNTS":
                raise ValueError("Current-batch account type mismatch")
            identity = task_row(run, source_name, timezone)
            shop, resource = identity["shop"], identity["resource"]
            if RESOURCE_TYPES.get(resource) != run.resource_type:
                raise ValueError("Current-batch resource type mismatch")
            cutoff = date.fromisoformat(identity["cutoff"])
            start, end = (date.fromisoformat(value) for value in identity["window"])
        else:
            if run.account_type != "AFFILIATE_ACCOUNTS":
                continue
            zone = ZoneInfo(timezone)
            shop = SOURCE_NAMES[source_name]
            resource = next(
                (
                    key
                    for key, value in RESOURCE_TYPES.items()
                    if value == run.resource_type
                ),
                None,
            )
            if resource is None:
                continue
            start = run.window_start.astimezone(zone).date()
            end = run.window_end.astimezone(zone).date() - timedelta(days=1)
            cutoff = None
        result.append(
            {
                "shop": shop,
                "resource": resource,
                "window": (start, end),
                "batch": batch,
                "cutoff": cutoff,
                "status": run.status,
                "fetched": run.fetched_count,
                "persisted": run.persisted_count,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
        )
    return result


def _job_batch_date(job_id: str) -> date | None:
    parts = job_id.split(":")
    if parts[0] == "affiliate-schedule" and len(parts) >= 3:
        value = parts[1]
    elif parts[:2] == ["affiliate", "live-batch"] and len(parts) >= 4:
        value = parts[2]
    else:
        return None
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
