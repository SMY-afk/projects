from __future__ import annotations

import json
import logging

from erp_api.core.config import get_settings
from erp_api.services.sample_time_left_refresh import (
    build_desired_time_left,
    list_time_left_targets,
    refresh_time_left_records,
)

logger = logging.getLogger(__name__)


async def refresh_sample_time_left_job(ctx) -> dict[str, int]:
    settings = get_settings()
    rows = await list_time_left_targets(
        ctx["database"], settings.sample_auto_assignment_shop_id_set
    )
    grouped = build_desired_time_left(rows)
    redis = ctx["redis"]
    result = {"updated": 0, "checked": 0, "busy_shops": 0, "failed_shops": 0}
    for (tenant_id, shop_id), desired in grouped.items():
        async with ctx["sample_shop_sync_lock"].acquire(tenant_id, shop_id) as acquired:
            if not acquired:
                result["busy_shops"] += 1
                continue
            try:
                cache_key = f"sample:time-left:v1:{tenant_id}:{shop_id}"
                record_ids = tuple(desired)
                cached = await redis.hmget(cache_key, *record_ids)
                dirty = {
                    record_id: desired[record_id]
                    for record_id, previous in zip(record_ids, cached, strict=True)
                    if (previous.decode() if isinstance(previous, bytes) else previous)
                    != json.dumps(
                        desired[record_id], ensure_ascii=False, sort_keys=True
                    )
                }
                if not dirty:
                    continue
                client = ctx["feishu_sample_client_router"].for_shop(shop_id)
                result["updated"] += await refresh_time_left_records(client, dirty)
                result["checked"] += len(dirty)
                await redis.hset(
                    cache_key,
                    mapping={
                        record_id: json.dumps(value, ensure_ascii=False, sort_keys=True)
                        for record_id, value in dirty.items()
                    },
                )
                await redis.expire(cache_key, 7 * 86_400)
            except Exception as error:  # noqa: BLE001 -- retry only this shop next cycle
                result["failed_shops"] += 1
                logger.error(
                    "sample_time_left_refresh_failed shop_id=%s error_type=%s",
                    shop_id,
                    type(error).__name__,
                )
    return result
