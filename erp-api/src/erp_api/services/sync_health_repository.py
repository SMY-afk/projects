from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsSyncCursor, AnalyticsSyncRun
from erp_api.models.shop import Shop


@dataclass(frozen=True)
class SyncRunSample:
    status: str
    error_category: str | None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class SyncCursorSample:
    last_success_at: datetime | None


@dataclass(frozen=True)
class SyncHealthResult:
    shop_id: UUID
    shop_name: str
    resource_type: str
    status: Literal["healthy", "degraded", "critical"]
    last_success_at: datetime | None
    delay_seconds: int | None
    failure_rate: float | None
    rate_limit_429_count: int
    dead_letter_count: int
    data_gap_count: int
    total_run_count: int
    successful_run_count: int
    window_hours: int


class SyncHealthRepository:
    def __init__(
        self,
        database: Database,
        *,
        window_hours: int = 168,
        expected_interval_minutes: int = 1440,
    ) -> None:
        self._database = database
        self._window_hours = window_hours
        self._expected_interval_minutes = expected_interval_minutes

    async def list_health(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID | None = None,
        now: datetime | None = None,
    ) -> list[SyncHealthResult]:
        measured_at = (now or datetime.now(UTC)).astimezone(UTC)
        cutoff = measured_at - timedelta(hours=self._window_hours)
        async for session in self._database.session(tenant_id):
            shop_query = select(Shop.id, Shop.shop_name).where(Shop.status == "active")
            if shop_id is not None:
                shop_query = shop_query.where(Shop.id == shop_id)
            shops = (
                await session.execute(shop_query.order_by(Shop.shop_name, Shop.id))
            ).all()
            if not shops:
                return []
            shop_ids = [row.id for row in shops]
            runs = (
                await session.scalars(
                    select(AnalyticsSyncRun).where(
                        AnalyticsSyncRun.shop_id.in_(shop_ids),
                        AnalyticsSyncRun.started_at >= cutoff,
                    )
                )
            ).all()
            cursors = (
                await session.scalars(
                    select(AnalyticsSyncCursor).where(
                        AnalyticsSyncCursor.shop_id.in_(shop_ids)
                    )
                )
            ).all()

        runs_by_key: dict[tuple[UUID, str], list[SyncRunSample]] = {}
        for run in runs:
            runs_by_key.setdefault((run.shop_id, run.resource_type), []).append(
                SyncRunSample(run.status, run.error_category, run.finished_at)
            )
        cursors_by_key = {
            (cursor.shop_id, cursor.resource_type): SyncCursorSample(
                cursor.last_success_at
            )
            for cursor in cursors
        }
        return [
            calculate_sync_health(
                shop_id=row.id,
                shop_name=row.shop_name,
                resource_type=resource_type,
                runs=runs_by_key.get((row.id, resource_type), []),
                cursor=cursors_by_key.get((row.id, resource_type)),
                now=measured_at,
                window_hours=self._window_hours,
                expected_interval_minutes=self._expected_interval_minutes,
            )
            for row in shops
            for resource_type in ("video", "live")
        ]


def calculate_sync_health(
    *,
    shop_id: UUID,
    shop_name: str,
    resource_type: str,
    runs: list[SyncRunSample],
    cursor: SyncCursorSample | None,
    now: datetime,
    window_hours: int,
    expected_interval_minutes: int,
) -> SyncHealthResult:
    terminal = [
        run for run in runs if run.status in {"succeeded", "failed", "dead_letter"}
    ]
    successful = sum(run.status == "succeeded" for run in terminal)
    failed = sum(run.status in {"failed", "dead_letter"} for run in terminal)
    failure_rate = round(failed / len(terminal), 4) if terminal else None
    rate_limits = sum(run.error_category == "rate_limited" for run in runs)
    dead_letters = sum(run.status == "dead_letter" for run in runs)
    success_times = [
        run.finished_at
        for run in terminal
        if run.status == "succeeded" and run.finished_at is not None
    ]
    if cursor and cursor.last_success_at is not None:
        success_times.append(cursor.last_success_at)
    last_success = (
        max(success_times, key=lambda value: value.astimezone(UTC))
        if success_times
        else None
    )
    delay_seconds = _delay_seconds(last_success, now)
    gaps = _gap_count(delay_seconds, expected_interval_minutes)
    status: Literal["healthy", "degraded", "critical"] = "healthy"
    if last_success is None or dead_letters or gaps >= 2:
        status = "critical"
    elif gaps or rate_limits or failed:
        status = "degraded"
    return SyncHealthResult(
        shop_id=shop_id,
        shop_name=shop_name,
        resource_type=resource_type,
        status=status,
        last_success_at=last_success,
        delay_seconds=delay_seconds,
        failure_rate=failure_rate,
        rate_limit_429_count=rate_limits,
        dead_letter_count=dead_letters,
        data_gap_count=gaps,
        total_run_count=len(runs),
        successful_run_count=successful,
        window_hours=window_hours,
    )


def _delay_seconds(last_success_at: datetime | None, now: datetime) -> int | None:
    if last_success_at is None:
        return None
    return max(0, int((now - last_success_at.astimezone(UTC)).total_seconds()))


def _gap_count(delay_seconds: int | None, expected_interval_minutes: int) -> int:
    if delay_seconds is None:
        return 1
    interval_seconds = expected_interval_minutes * 60
    return max(0, math.ceil(delay_seconds / interval_seconds) - 1)
