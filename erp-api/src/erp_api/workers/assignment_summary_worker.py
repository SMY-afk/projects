from __future__ import annotations

import asyncio
import logging
import time

from redis.asyncio import Redis

from erp_api.core.config import get_settings
from erp_api.core.logging import configure_logging
from erp_api.infrastructure.database import Database
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_assignment_summary_client import (
    FeishuAssignmentSummaryClient,
)
from erp_api.services.sample_assignment_summary_repository import (
    SampleAssignmentSummaryRepository,
)
from erp_api.services.sample_assignment_summary_service import (
    ASSIGNMENT_SUMMARY_REVISION_KEY,
    SampleAssignmentSummaryService,
)

logger = logging.getLogger("erp_api.assignment_summary")
CHANGE_CHECK_INTERVAL_SECONDS = 60


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.feishu_assignment_summary_sync_enabled:
        raise RuntimeError("Assignment summary sync is disabled.")
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    client_options = {
        "app_id": settings.feishu_app_id,
        "app_secret": settings.feishu_app_secret.get_secret_value(),
        "base_token": settings.feishu_sample_base_token.get_secret_value(),
    }
    assignment_client = FeishuAssignmentRecordClient(
        **client_options,
        table_id=settings.feishu_bd_assignment_record_table_id,
    )
    summary_client = FeishuAssignmentSummaryClient(
        **client_options,
        table_id=settings.feishu_assignment_summary_table_id,
    )
    service = SampleAssignmentSummaryService(
        SampleAssignmentSummaryRepository(database),
        assignment_client,
        summary_client,
        allowed_shop_ids=settings.assignment_summary_shop_id_set,
        bd_names=settings.assignment_summary_bd_names,
        bd_aliases=settings.feishu_assignment_summary_bd_aliases,
    )
    interval = settings.feishu_assignment_summary_sync_interval_seconds
    paid_service = None
    if settings.feishu_refundable_assignment_summary_table_id:
        if not settings.feishu_refundable_assignment_record_table_id:
            raise RuntimeError("Refundable summary requires its assignment source table")
        paid_service = SampleAssignmentSummaryService(
            SampleAssignmentSummaryRepository(database),
            FeishuAssignmentRecordClient(**client_options, table_id=settings.feishu_refundable_assignment_record_table_id),
            FeishuAssignmentSummaryClient(**client_options, table_id=settings.feishu_refundable_assignment_summary_table_id),
            allowed_shop_ids=settings.assignment_summary_shop_id_set,
            bd_names=settings.assignment_summary_bd_names,
            bd_aliases=settings.feishu_assignment_summary_bd_aliases,
            sample_type="refundable",
        )
    last_revision = None
    last_sync_at = 0.0
    try:
        while True:
            try:
                revision = await redis.get(ASSIGNMENT_SUMMARY_REVISION_KEY)
                if (
                    last_sync_at
                    and revision == last_revision
                    and time.monotonic() - last_sync_at < interval
                ):
                    await asyncio.sleep(CHANGE_CHECK_INTERVAL_SECONDS)
                    continue
                result = await service.sync()
                if paid_service is not None:
                    paid_result = await paid_service.sync()
                    logger.info("Refundable assignment summary sync completed",
                                extra={"source_count": paid_result.source_count,
                                       "updated_count": paid_result.updated_count})
                last_revision = revision
                last_sync_at = time.monotonic()
                logger.info(
                    "Assignment summary sync completed",
                    extra={
                        "source_count": result.source_count,
                        "updated_count": result.updated_count,
                        "created_count": result.created_count,
                        "locked_count": result.locked_count,
                    },
                )
            except Exception:
                logger.exception("Assignment summary sync failed")
                await asyncio.sleep(60)
                continue
            await asyncio.sleep(CHANGE_CHECK_INTERVAL_SECONDS)
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
