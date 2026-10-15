from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    TERMINAL_SAMPLE_STATUSES,
)
from erp_api.workers.sample_queue import SAMPLE_QUEUE_NAME


def _arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Queue one shop's sample sync.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--shop-id", required=True, type=UUID)
    parser.add_argument(
        "--source-type",
        required=True,
        choices=("official_api", "hubstudio_cdp"),
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=("active", "terminal", "full"),
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--enqueue", action="store_true")
    return parser.parse_args(argv)


async def _run(args):
    _validate_options(args)
    settings = get_settings()
    database = Database(settings.database_url)
    queue = None
    try:
        await _require_exact_shop(database, args.tenant_id, args.shop_id)
        plan = {
            "tenant_id": str(args.tenant_id),
            "shop_id": str(args.shop_id),
            "source_type": args.source_type,
            "mode": args.mode,
            "dry_run": bool(args.dry_run),
        }
        if args.dry_run:
            return {"status": "dry_run", **plan}
        if args.source_type == "hubstudio_cdp":
            raise ValueError(
                "HubStudio/CDP execution requires the explicitly bound listener."
            )
        queue = await create_pool(
            RedisSettings.from_dsn(settings.redis_url),
            default_queue_name=SAMPLE_QUEUE_NAME,
        )
        job_id = (
            f"manual-sample:{args.tenant_id}:{args.shop_id}:"
            f"{args.source_type}:{args.mode}:{uuid4().hex}"
        )
        if args.mode == "full":
            job = await queue.enqueue_job(
                "reconcile_sample_applications_job",
                str(args.tenant_id),
                str(args.shop_id),
                args.source_type,
                False,
                _job_id=job_id,
            )
        else:
            statuses = (
                sorted(ACTIVE_SAMPLE_STATUSES)
                if args.mode == "active"
                else sorted(TERMINAL_SAMPLE_STATUSES)
            )
            job = await queue.enqueue_job(
                "sync_sample_applications_job",
                str(args.tenant_id),
                str(args.shop_id),
                args.mode,
                statuses,
                args.source_type,
                False,
                _job_id=job_id,
            )
        if job is None:
            raise RuntimeError("Targeted sample sync job could not be queued.")
        return {"status": "queued", "job_id": job_id, **plan}
    finally:
        if queue is not None:
            await queue.aclose()
        await database.dispose()


def _validate_options(args) -> None:
    if args.source_type not in {"official_api", "hubstudio_cdp"}:
        raise ValueError("Sample source type is invalid.")
    if args.mode not in {"active", "terminal", "full"}:
        raise ValueError("Sample sync mode is invalid.")
    if bool(args.dry_run) == bool(args.enqueue):
        raise ValueError("Choose exactly one of dry_run or enqueue.")


async def _require_exact_shop(database, tenant_id: UUID, shop_id: UUID) -> None:
    async with database.system_session_factory() as session:
        matched = await session.scalar(
            select(Shop.id).where(
                Shop.tenant_id == tenant_id,
                Shop.id == shop_id,
                Shop.platform == "tiktok",
                Shop.status == "active",
            )
        )
    if matched != shop_id:
        raise ValueError("Target must match one active TikTok shop in the tenant.")


def main() -> None:
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
