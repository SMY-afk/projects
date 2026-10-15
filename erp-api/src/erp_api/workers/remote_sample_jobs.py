"""Server-side business processing for an already persisted local capture."""

from __future__ import annotations

from uuid import UUID

from arq import Retry
from sqlalchemy import select

from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.services.hubstudio_sample_ingest_service import HubStudioSampleIngestResult


async def process_remote_sample_batch_job(
    ctx, tenant_id: str, shop_id: str, batch_id: str
):
    parsed_tenant_id = UUID(tenant_id)
    parsed_shop_id = UUID(shop_id)
    parsed_batch_id = UUID(batch_id)
    async with ctx["sample_shop_sync_lock"].acquire(
        parsed_tenant_id, parsed_shop_id
    ) as acquired:
        if not acquired:
            raise Retry(defer=ctx.get("sample_shop_lock_retry_seconds", 30))
        async with ctx["database"].system_session_factory() as session:
            batch = await session.scalar(
                select(SampleIngestBatch).where(
                    SampleIngestBatch.id == parsed_batch_id,
                    SampleIngestBatch.tenant_id == parsed_tenant_id,
                    SampleIngestBatch.shop_id == parsed_shop_id,
                    SampleIngestBatch.source_type == "hubstudio_cdp",
                    SampleIngestBatch.status == "complete",
                    SampleIngestBatch.source_identity.like("remote:%"),
                )
            )
        if batch is None:
            raise LookupError("Completed remote sample batch was not found")
        evidence = batch.completeness_evidence or {}
        source_result = HubStudioSampleIngestResult(
            status="succeeded",
            batch_id=batch.id,
            page_count=batch.page_count,
            record_count=batch.captured_total,
            request_ids=(),
            application_ids=tuple(UUID(item) for item in evidence["application_ids"]),
            changed_application_ids=tuple(
                UUID(item) for item in evidence["changed_application_ids"]
            ),
            obsolete_platform_application_ids=frozenset(
                evidence["obsolete_platform_application_ids"]
            ),
        )
        result = await ctx["sample_shop_pipeline_service"].complete_after_source(
            tenant_id=parsed_tenant_id,
            shop_id=parsed_shop_id,
            source_type="hubstudio_cdp",
            source_results=(source_result,),
        )
        return {"batch_id": batch_id, "status": result.status}
