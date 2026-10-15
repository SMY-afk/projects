"""Read-only official candidates and exact related-row preview for metadata."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Uuid, cast, select, text

from erp_api.models.sample_application import SampleApplication as App
from erp_api.models.sample_application_workflow import (
    SampleApplicationWorkflow as Workflow,
)
from erp_api.models.sample_ingest_batch import SampleIngestBatch as Batch
from erp_api.models.sample_sync_run import SampleSyncRun as Run
from scripts.local_sample_metadata_rules import (
    LOCAL_SHOP,
    LOCAL_TENANT,
    account,
    eligible_candidate,
    fresh,
    require_manifest,
)

TENANT, SHOP = UUID(LOCAL_TENANT), UUID(LOCAL_SHOP)


async def require_source(database, *, now=None):
    now = now or datetime.now(UTC)
    async with database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        latest = (await session.execute(select(Run, Batch).join(
            Batch, Batch.id == cast(Run.source_batch_ids[0].astext, Uuid)
        ).where(
            Run.tenant_id == TENANT, Run.shop_id == SHOP, Run.sample_type == "free",
            Run.source_type == "official_api", Run.sync_type == "source_to_postgres",
            Batch.tenant_id == TENANT, Batch.shop_id == SHOP,
            Batch.sample_type == "free", Batch.source_type == "official_api",
            Batch.source_identity == "sample_applications:active:PENDING",
        ).order_by(Run.started_at.desc()).limit(1))).one_or_none()
    if latest is None:
        raise RuntimeError("metadata_source_missing")
    run, batch = latest
    if (run.status != "succeeded" or batch.status != "complete"
            or not fresh(run.finished_at, now) or not fresh(batch.finished_at, now)
            or batch.page_count < 1
            or batch.expected_total is not None and batch.expected_total != batch.captured_total):
        raise RuntimeError("metadata_source_not_complete_success")
    return {"source_batch_id": str(batch.id), "source_success_at": run.finished_at.isoformat()}


async def candidates(database, activation, *, now=None):
    now = now or datetime.now(UTC)
    if not isinstance(activation, datetime) or activation.utcoffset() is None:
        raise RuntimeError("metadata_activation_missing")
    proof = await require_source(database, now=now)
    async with database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await session.execute(select(App, Workflow, Batch)
            .join(Workflow, Workflow.sample_application_id == App.id)
            .join(Batch, Batch.id == App.source_capture_id).where(
                App.tenant_id == TENANT, App.shop_id == SHOP,
                App.source_type == "official_api", App.sample_type == "free",
                App.platform_status == "PENDING", App.is_current_projection.is_(True),
                App.is_approvable.is_(True), App.approve_expiration_at > now,
                App.first_seen_at >= activation,
                App.raw_payload["is_proactive_invitation"].as_string().is_(None),
                Workflow.tenant_id == TENANT, Workflow.shop_id == SHOP,
                Workflow.assigned_bd_name.is_(None), Workflow.assignment_version == 0,
            ).order_by(App.source_observed_at.desc(), App.id).limit(500))).all()
    eligible = [app for app, workflow, batch in rows
                if eligible_candidate(app, workflow, batch, now, activation)]
    return {"tenant_id": LOCAL_TENANT, "shop_id": LOCAL_SHOP,
            "checked_at": now.isoformat(), **proof,
            "rows": [{"id": str(app.id), "platform_application_id": app.platform_application_id,
                      "creator_username": app.creator_username} for app in eligible]}


async def preview_related(database, manifest, groups, activation, *, now=None):
    now = now or datetime.now(UTC)
    targets = require_manifest(manifest)
    raw_ids = {item["application_id"] for group in groups for item in group["products"]}
    await require_source(database, now=now)
    async with database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        initial = (await session.execute(select(App, Workflow, Batch)
            .join(Workflow, Workflow.sample_application_id == App.id)
            .join(Batch, Batch.id == App.source_capture_id).where(
                App.tenant_id == TENANT, App.shop_id == SHOP,
                App.platform_application_id.in_(targets),
                Workflow.tenant_id == TENANT, Workflow.shop_id == SHOP,
            ))).all()
        if len(initial) != len(targets):
            raise RuntimeError("metadata_manifest_pg_missing")
        for app, workflow, batch in initial:
            target = targets[app.platform_application_id]
            if (str(app.id) != target["id"] or account(app.creator_username)
                    != account(target["creator_username"])):
                raise RuntimeError("metadata_manifest_pg_identity_changed")
            # An uncertain prior attempt may already have set the marker. All
            # other eligibility checks must still pass before idempotent retry.
            if not eligible_candidate(app, workflow, batch, now, activation,
                                      allow_applied_marker=True):
                raise RuntimeError("metadata_candidate_no_longer_eligible")
        creator_ids = {app.creator_open_id for app, _, _ in initial}
        related = (await session.scalars(select(App).where(
            App.tenant_id == TENANT, App.shop_id == SHOP, App.source_type == "official_api",
            App.creator_open_id.in_(creator_ids),
        ))).all()
        if any(app.sample_type != "free" for app in related):
            raise RuntimeError("metadata_related_sample_type_ambiguous")
        by_platform = {app.platform_application_id: app for app in related}
        if not raw_ids <= by_platform.keys():
            raise RuntimeError("metadata_raw_member_not_official_persisted")
        for group in groups:
            if any(account(by_platform[item["application_id"]].creator_username)
                   != account(group["creator"]["username"]) for item in group["products"]):
                raise RuntimeError("metadata_raw_member_creator_changed")
            if any((by_platform[item["application_id"]].raw_payload or {}).get(
                "manual_assignment_deleted") is True for item in group["products"]):
                raise RuntimeError("metadata_manual_deletion_preserved")
    return {app.id for app in related}, initial[0][0].id


async def verify_applied(database, groups, related_ids):
    expected = {item["application_id"]: item for group in groups for item in group["products"]}
    async with database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await session.scalars(select(App).where(
            App.tenant_id == TENANT, App.shop_id == SHOP, App.id.in_(related_ids),
            App.platform_application_id.in_(expected),
        ))).all()
    if len(rows) != len(expected):
        raise RuntimeError("metadata_readback_members_missing")
    for app in rows:
        product = expected[app.platform_application_id]
        raw = app.raw_payload
        if (app.source_type != "official_api" or app.sample_type != "free"
                or raw.get("is_proactive_invitation") is not product["is_proactive_invitation"]
                or raw.get("application_source_type") != product["application_source_type"]
                or app.tiktok_applied_at != datetime.fromtimestamp(product["application_time"], UTC)):
            raise RuntimeError("metadata_readback_mismatch")
