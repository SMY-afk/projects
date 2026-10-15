"""Read only the local shop's official free-sample watermarks and source policy."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Uuid, cast, select, text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.services.sample_source_policy import (
    SampleSourcePolicy,
    SampleSourcePolicyError,
    SampleSourcePolicyRepository,
)

TENANT = UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26")
SHOP = UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10")


async def main():
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            latest = await session.scalar(
                select(SampleSyncRun)
                .join(SampleIngestBatch, SampleIngestBatch.id == cast(
                    SampleSyncRun.source_batch_ids[0].astext, Uuid))
                .where(
                    SampleSyncRun.tenant_id == TENANT,
                    SampleSyncRun.shop_id == SHOP,
                    SampleSyncRun.sample_type == "free",
                    SampleSyncRun.sync_type == "source_to_postgres",
                    SampleSyncRun.source_type == "official_api",
                    SampleIngestBatch.tenant_id == TENANT,
                    SampleIngestBatch.shop_id == SHOP,
                    SampleIngestBatch.source_identity == "sample_applications:active:PENDING",
                )
                .order_by(SampleSyncRun.started_at.desc())
                .limit(1)
            )
            row = {
                "shop": "local",
                "checked_at": datetime.now(UTC).isoformat(),
                "state": "failed",
            }
            if latest and latest.status == "succeeded" and latest.finished_at:
                row.update(
                    state="idle",
                    last_success_at=latest.finished_at.isoformat(),
                    next_due=(latest.started_at + timedelta(seconds=300)).isoformat(),
                )
        try:
            await SampleSourcePolicy(
                SampleSourcePolicyRepository(database)
            ).require_hubstudio_fallback(
                tenant_id=TENANT,
                shop_id=SHOP,
                platform_shop_id="9136806951995371293",
                official_access_state="missing_scope",
            )
            row["source_policy_result"] = "accepted"
        except SampleSourcePolicyError as error:
            row["source_policy_result"] = error.code
        print(json.dumps(row))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
