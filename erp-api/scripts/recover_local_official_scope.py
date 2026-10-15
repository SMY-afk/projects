"""Recover an explicit local-shop manifest through the unchanged business gates."""

import argparse
import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
)
from erp_api.services.sample_assignment_summary_service import (
    ASSIGNMENT_SUMMARY_REVISION_KEY,
)
from erp_api.services.sample_bd_invitation_ai_priority import AiInvitationSnapshotStore
from erp_api.services.sample_business_readiness import SampleBusinessReadiness
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from scripts.local_official_cooperation_preview import (
    require_existing_cooperation_allowed,
)
from scripts.sample_watch_freshness import SHOPS, TENANT_ID

SHOP = SHOPS["local"]


async def main(args):
    manifest = json.loads(Path(args.manifest).read_text())
    capture = json.loads(Path(args.capture).read_text())
    if manifest["tenant_id"] != str(TENANT_ID) or manifest["shop_id"] != str(SHOP):
        raise RuntimeError("Recovery manifest scope mismatch")
    if capture["shop_id"] != str(SHOP) or capture["page_count"] < 1:
        raise RuntimeError("Recovery capture scope mismatch")
    age = (
        datetime.now(UTC) - datetime.fromisoformat(capture["observed_at"])
    ).total_seconds()
    if not 0 <= age <= 900:
        raise RuntimeError("Recovery browser evidence is stale")
    targets = {row["platform_application_id"]: row for row in manifest["rows"]}
    if args.application_id:
        if args.application_id not in targets:
            raise RuntimeError("Application is not in the approved recovery manifest")
        targets = {args.application_id: targets[args.application_id]}
    applications = [
        app
        for app in capture["applications"]
        if targets.keys() & {p["application_id"] for p in app["products"]}
    ]
    products = {p["application_id"]: p for app in applications for p in app["products"]}
    if not targets.keys() <= products.keys():
        raise RuntimeError("Recovery capture is missing requested applications")
    for app in applications:
        creator = app["creator"]
        for product in app["products"]:
            target = targets.get(product["application_id"])
            if target and (
                creator["username"].lstrip("@").casefold()
                != target["creator_username"].lstrip("@").casefold()
            ):
                raise RuntimeError("Recovery RAW creator identity mismatch")
    if any(
        not isinstance(products[key].get("is_proactive_invitation"), bool)
        or not products[key].get("application_time")
        for key in targets
    ):
        raise RuntimeError("Recovery invitation or request-date evidence is incomplete")
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            current = (
                await session.scalars(
                    select(SampleApplication).where(
                        SampleApplication.tenant_id == TENANT_ID,
                        SampleApplication.shop_id == SHOP,
                        SampleApplication.platform_application_id.in_(targets),
                    )
                )
            ).all()
        if len(current) != len(targets):
            raise RuntimeError("Recovery PostgreSQL scope is incomplete")
        valid = {
            a.platform_application_id
            for a in current
            if a.platform_status == "PENDING"
            and a.is_approvable is True
            and a.approve_expiration_at
            and a.approve_expiration_at > datetime.now(UTC)
            and not a.raw_payload.get("manual_assignment_deleted")
        }
        if valid != targets.keys():
            raise RuntimeError(
                "Recovery target changed or expired; re-preview required"
            )
        for app in current:
            if (
                app.creator_open_id
                != targets[app.platform_application_id]["creator_open_id"]
            ):
                raise RuntimeError("Recovery creator identity changed")
        print(
            f"EXACT_SCOPE_VERIFIED applications={len(current)} groups={len(applications)}",
            flush=True,
        )
        if not args.apply:
            print("PREVIEW_ONLY", flush=True)
            return

        async def allocation_changed():
            await redis.incr(ASSIGNMENT_SUMMARY_REVISION_KEY)

        snapshot = (
            AiInvitationSnapshotStore(
                redis,
                spreadsheet_token=settings.feishu_ai_invitation_sheet_token,
                sheet_id=settings.feishu_ai_invitation_sheet_id,
            )
            if settings.feishu_ai_invitation_sheet_token
            and settings.feishu_ai_invitation_sheet_id
            else None
        )
        services = build_sample_application_services(
            settings,
            database,
            ai_snapshot_store=snapshot,
            assignment_change_notifier=allocation_changed,
        )
        async with AsyncExitStack() as stack:
            lock = SampleShopSyncLock(database)
            deadline = asyncio.get_running_loop().time() + 55
            while True:
                context = lock.acquire(TENANT_ID, SHOP)
                if await context.__aenter__():
                    stack.push_async_exit(context)
                    break
                await context.__aexit__(None, None, None)
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError("Local sample shop is busy; no recovery applied")
                await asyncio.sleep(0.5)
            await SampleBusinessReadiness._require_readyz()
            print("SOURCE_REFRESH_PENDING_ONLY", flush=True)
            source = await services["sample_application_sync_service"].sync(
                TENANT_ID,
                SHOP,
                mode="active",
                status="PENDING",
            )
            if source.status != "succeeded":
                raise RuntimeError("Local current pending source is incomplete")
            if not {UUID(row["id"]) for row in targets.values()} <= set(
                source.application_ids
            ):
                raise RuntimeError(
                    "Requested applications left the latest pending window"
                )
            await SampleBusinessReadiness().require_ready(
                tenant_id=TENANT_ID, shop_id=SHOP
            )
            print("LOCAL_AND_DAILY_GATES=ok", flush=True)
            if (
                datetime.now(UTC) - datetime.fromisoformat(capture["observed_at"])
            ).total_seconds() > 900:
                raise RuntimeError("Browser evidence expired during source refresh")
            enriched = await SampleApplicationTimeEnrichmentService(database).enrich(
                tenant_id=TENANT_ID,
                shop_id=SHOP,
                applications=applications,
                observed_at=datetime.fromisoformat(capture["observed_at"]),
                request_id=capture["request_id"],
            )
            print(
                f"RAW_ENRICHED matched={enriched.matched_count} updated={enriched.updated_count}",
                flush=True,
            )
            if args.enrich_only:
                print("SOURCE_ENRICHMENT_ONLY_NO_FEISHU", flush=True)
                return
            if args.application_id:
                await require_existing_cooperation_allowed(
                    services["sample_cooperation_precheck_service"],
                    database,
                    TENANT_ID,
                    SHOP,
                    args.application_id,
                )
            result = await services[
                "sample_shop_pipeline_service"
            ].complete_after_source(
                tenant_id=TENANT_ID,
                shop_id=SHOP,
                source_type="official_api",
                source_results=(enriched,),
            )
            assignment = result.auto_assignment_result
            summary = {
                "status": result.status,
                "scope_applications": len(targets),
                "scope_projection_ids": [str(x) for x in enriched.application_ids],
                "assigned_count": assignment.assigned_count if assignment else 0,
                "blocked_count": assignment.blocked_count if assignment else 0,
                "assignment_items": asdict(assignment) if assignment else None,
                "notification_results": [
                    asdict(x) for x in result.notification_results
                ],
                "feishu_result": asdict(result.feishu_result)
                if result.feishu_result
                else None,
            }
            Path(args.output).write_text(
                json.dumps(summary, ensure_ascii=False, default=str)
            )
            print(
                json.dumps(
                    {
                        key: summary[key]
                        for key in (
                            "status",
                            "scope_applications",
                            "assigned_count",
                            "blocked_count",
                            "feishu_result",
                        )
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--capture", required=True)
    parser.add_argument("--output", default="/tmp/local-official-recovery-result.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--enrich-only", action="store_true")
    parser.add_argument("--application-id")
    asyncio.run(main(parser.parse_args()))
