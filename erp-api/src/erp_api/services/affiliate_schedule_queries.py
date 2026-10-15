from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_daily_queries import split_bounded_queries

BEIJING = ZoneInfo("Asia/Shanghai")
DAILY_RUN_TIME = time(23, 30)
DAILY_CAPTURE_WINDOW = timedelta(minutes=15)
DAILY_RETRY_WINDOW = timedelta(hours=8, minutes=30)
DAILY_COLLECTION_DELAY = timedelta(minutes=20)
ROLLING_CHUNK_DAYS = 30


@dataclass(frozen=True)
class ScheduledShop:
    tenant_id: UUID
    shop_id: UUID
    timezone: str
    currency: str
    source_name: str = ""


def latest_due_schedule_date(now: datetime) -> date:
    local = _utc(now).astimezone(BEIJING)
    if local.time().replace(tzinfo=None) < DAILY_RUN_TIME:
        return local.date() - timedelta(days=1)
    return local.date()


def previous_shop_day(now: datetime, timezone: str) -> date:
    return _utc(now).astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)


def daily_capture_window_open(now: datetime) -> bool:
    local = _utc(now).astimezone(BEIJING)
    window_start = _local_capture_window_start(local)
    return window_start <= local < window_start + DAILY_CAPTURE_WINDOW


def daily_retry_window_open(now: datetime) -> bool:
    local = _utc(now).astimezone(BEIJING)
    window_start = datetime.combine(
        latest_due_schedule_date(now),
        DAILY_RUN_TIME,
        tzinfo=BEIJING,
    )
    return window_start <= local < window_start + DAILY_RETRY_WINDOW


def daily_collection_window_open(now: datetime) -> bool:
    local = _utc(now).astimezone(BEIJING)
    availability_start = datetime.combine(
        latest_due_schedule_date(now),
        DAILY_RUN_TIME,
        tzinfo=BEIJING,
    )
    collection_start = availability_start + DAILY_COLLECTION_DELAY
    return collection_start <= local < availability_start + DAILY_RETRY_WINDOW


def daily_capture_window_start(now: datetime) -> datetime:
    local = _utc(now).astimezone(BEIJING)
    return _local_capture_window_start(local).astimezone(UTC)


def latest_due_capture_window_start(now: datetime) -> datetime:
    schedule_date = latest_due_schedule_date(now)
    return datetime.combine(schedule_date, DAILY_RUN_TIME, tzinfo=BEIJING).astimezone(
        UTC
    )


def scheduled_creator_query(
    shop: ScheduledShop, latest_available: date
) -> AffiliateCenterQuery:
    return scheduled_affiliate_query(
        shop, latest_available, AffiliateCenterResource.CREATORS
    )


def scheduled_affiliate_query(
    shop: ScheduledShop,
    latest_available: date,
    resource: AffiliateCenterResource,
) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=resource,
        shop_id=shop.shop_id,
        window_start=latest_available,
        window_end=latest_available,
        shop_timezone=shop.timezone,
        currency=shop.currency,
        filters={},
    )


def scheduled_affiliate_queries(
    shop: ScheduledShop,
    latest_available: date,
    resource: AffiliateCenterResource,
) -> list[AffiliateCenterQuery]:
    full_window = AffiliateCenterQuery(
        resource=resource,
        shop_id=shop.shop_id,
        window_start=latest_available - relativedelta(months=2),
        window_end=latest_available,
        shop_timezone=shop.timezone,
        currency=shop.currency,
        filters={},
    )
    return split_bounded_queries(full_window, max_days=ROLLING_CHUNK_DAYS)


def scheduled_query_job_base(
    query: AffiliateCenterQuery, batch_date: date, cutoff: date
) -> str:
    resource = query.resource.value.removesuffix("s")
    return (
        f"affiliate-schedule:{batch_date:%Y%m%d}:{cutoff:%Y%m%d}:"
        f"{query.shop_id}:{resource}:"
        f"{query.window_start:%Y%m%d}-{query.window_end:%Y%m%d}"
    )


def scheduled_job_base(schedule_date: date, shop_id: UUID) -> str:
    return scheduled_resource_job_base(
        schedule_date, shop_id, AffiliateCenterResource.CREATORS
    )


def scheduled_resource_job_base(
    schedule_date: date,
    shop_id: UUID,
    resource: AffiliateCenterResource,
) -> str:
    return (
        f"affiliate-schedule:{schedule_date:%Y%m%d}:{shop_id}:"
        f"{resource.value.removesuffix('s')}"
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Affiliate schedule clock must include a UTC offset.")
    return value.astimezone(UTC)


def _local_capture_window_start(local: datetime) -> datetime:
    return datetime.combine(local.date(), DAILY_RUN_TIME, tzinfo=BEIJING)
