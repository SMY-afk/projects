"""Publish existing monitor results without blocking order or tracking polling."""
import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError

from erp_api.core.config import get_settings
from erp_api.services.logistics_feishu_client import LogisticsFeishuClient
from erp_api.services.logistics_feishu_sync import sync_once

CONFIG_KEY = "logistics:feishu:config"
HEALTH_KEY = "logistics:feishu:health"
logger = logging.getLogger("erp_api.logistics_feishu")


def configured_client(config):
    settings = get_settings()
    profile = config["appProfile"]
    if profile not in {"primary", "new"}:
        raise ValueError("Invalid Feishu app profile")
    prefix = "feishu_new" if profile == "new" else "feishu"
    app_id, secret = getattr(settings, prefix + "_app_id"), getattr(settings, prefix + "_app_secret")
    if not app_id or not secret:
        raise ValueError("The selected Feishu application is not configured")
    return LogisticsFeishuClient(app_id=app_id, app_secret=secret.get_secret_value(),
                                base_token=config["baseToken"], table_id=config["tableId"])


async def feishu_loop(state, service):
    client, previous_config = None, None
    while True:
        started, interval = time.monotonic(), 60
        try:
            raw = await state.redis.get(CONFIG_KEY)
            config = json.loads(raw) if raw else {}
            if config.get("enabled"):
                if config != previous_config:
                    client, previous_config = configured_client(config), config
                interval = await sync_cycle(state, service, client, config)
        except Exception as error:
            # Feishu is an independent delivery boundary; it must not terminate polling.
            code = getattr(error, "error_code", type(error).__name__)
            logger.exception("Logistics Feishu cycle failed: %s", code)
            try:
                await state.redis.set(HEALTH_KEY, json.dumps({"at": datetime.now(UTC).isoformat(),
                    "status": "retrying", "errorCode": code}), ex=86400)
            except RedisError:
                logger.warning("Logistics Feishu health storage is unavailable")
            interval = max(interval, 120)
        await asyncio.sleep(max(1, interval - (time.monotonic() - started)))


def schedule_window(schedule, now, health):
    """Return the due wall-clock slot and the next slot, using persisted success."""
    timezone = ZoneInfo(schedule["timezone"])
    hours = schedule["hours"]
    if not hours or any(type(hour) is not int or not 0 <= hour <= 23 for hour in hours) or len(set(hours)) != len(hours):
        raise ValueError("Invalid logistics Feishu schedule hours")
    start = datetime.fromisoformat(schedule["startAt"])
    if start.tzinfo is None or now.tzinfo is None:
        raise ValueError("Schedule timestamps must include a timezone")
    local_start = start.astimezone(timezone)
    if local_start.hour not in hours or any((local_start.minute, local_start.second, local_start.microsecond)):
        raise ValueError("Schedule activation must match a configured slot")
    if now < start:
        return None, start.astimezone(UTC)
    local = now.astimezone(timezone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    slots = [(midnight + timedelta(days=day, hours=hour)).astimezone(UTC)
             for day in (-1, 0, 1) for hour in hours]
    slot = max(value for value in slots if value <= now)
    next_slot = min(value for value in slots if value > now)
    completed = health.get("scheduledFor") if health.get("status") == "ok" else None
    if completed and datetime.fromisoformat(completed) >= slot:
        return None, next_slot
    return slot, slot


async def sync_cycle(state, service, client, config, *, now=None):
    """Publish a due slot under the existing lease; never publish merely on startup."""
    schedule = config.get("dailySchedule")
    interval = 60 if schedule else max(60, int(config.get("intervalSeconds", 60)))

    async def due():
        current = now or datetime.now(UTC)
        health = json.loads(await state.redis.get(HEALTH_KEY) or "{}")
        slot, next_run = schedule_window(schedule, current, health)
        return slot, max(1, min(60, (next_run - current).total_seconds()))

    scheduled_for = None
    if schedule:
        scheduled_for, interval = await due()
        if scheduled_for is None:
            return interval
    owner = str(uuid4())
    lock = f"logistics:feishu:lock:{config['tenantId']}:{config['tableId']}"
    acquired = bool(await state.redis.set(lock, owner, nx=True, ex=300))
    if not acquired:
        return 60 if schedule else interval
    try:
        if schedule:
            scheduled_for, interval = await due()
            if scheduled_for is None:
                return interval
        async with asyncio.timeout(240):
            receipt = await sync_once(state, service, client, config, apply=True)
        completed_at = now or datetime.now(UTC)
        health = {"at": completed_at.isoformat(), "status": "ok", **receipt}
        if schedule:
            health["scheduledFor"] = scheduled_for.isoformat()
            _, next_run = schedule_window(schedule, completed_at, health)
            health["nextScheduledFor"] = next_run.isoformat()
        await state.redis.set(HEALTH_KEY, json.dumps(health), ex=86400)
        return 60 if schedule else interval
    finally:
        try:
            await state.redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
                                   1, lock, owner)
        except RedisError:
            logger.warning("Logistics Feishu lease release will wait for expiry")
