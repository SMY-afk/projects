from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
)

BD_NAMES = frozenset({"李鸿程", "吴洵涛", "刘诚"})
RULE_VERSION = "bd-v1-smoke"
SHOP_NAME = "Akeleo Toys"


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        before = await _smoke_rows(database, args.tenant_id, args.shop_id)
        _validate_targets(before)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "shop": SHOP_NAME,
                    "target_count": len(before),
                    "notifications": _notification_statuses(before),
                    "profiles": _profile_summary(before),
                    "apply": args.apply,
                },
                ensure_ascii=False,
            )
        )
        if not args.apply:
            return
        result = await SampleNotificationProfileEnrichmentService(
            database,
            limit=3,
        ).enrich(
            tenant_id=args.tenant_id,
            shop_id=args.shop_id,
            outbox_ids=frozenset(outbox.id for outbox, _application, _shop in before),
        )
        after = await _smoke_rows(database, args.tenant_id, args.shop_id)
        _validate_targets(after)
        if _notification_statuses(after) != _notification_statuses(before):
            raise RuntimeError("Profile enrichment changed notification state.")
        if result.unavailable_count:
            raise RuntimeError("A smoke profile could not be enriched from real data.")
        if any(not _has_profile(application) for _, application, _ in after):
            raise RuntimeError("Profile enrichment database verification failed.")
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "shop": SHOP_NAME,
                    "result": {
                        "enriched": result.enriched_count,
                        "unavailable": result.unavailable_count,
                        "skipped": result.skipped_count,
                    },
                    "notifications_unchanged": True,
                    "profiles": _profile_summary(after),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def _smoke_rows(database, tenant_id, shop_id):
    statement = (
        select(SampleNotificationOutbox, SampleApplication, Shop)
        .join(
            SampleApplication,
            SampleApplication.id == SampleNotificationOutbox.sample_application_id,
        )
        .join(Shop, Shop.id == SampleNotificationOutbox.shop_id)
        .where(
            SampleNotificationOutbox.tenant_id == tenant_id,
            SampleNotificationOutbox.shop_id == shop_id,
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            Shop.tenant_id == tenant_id,
            Shop.shop_name == SHOP_NAME,
            SampleNotificationOutbox.payload["source_event_id"].astext.like(
                f"bd-auto:{RULE_VERSION}:%"
            ),
        )
        .order_by(SampleNotificationOutbox.created_at)
    )
    async with database.system_session_factory() as session:
        return tuple((await session.execute(statement)).all())


def _validate_targets(rows) -> None:
    if len(rows) != 3:
        raise RuntimeError("Expected exactly three live smoke assignments.")
    names = {_bd_name(outbox) for outbox, _application, _shop in rows}
    if names != BD_NAMES:
        raise RuntimeError("Live smoke BD coverage is incomplete.")


def _bd_name(outbox) -> str:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    name = payload.get("assigned_bd_name")
    if not isinstance(name, str) or name not in BD_NAMES:
        raise RuntimeError("Unexpected BD in live smoke assignment.")
    return name


def _notification_statuses(rows) -> dict[str, str]:
    return {_bd_name(outbox): outbox.status for outbox, _application, _shop in rows}


def _profile_summary(rows) -> dict[str, object]:
    result = {}
    for outbox, application, _shop in rows:
        snapshot = (
            application.creator_profile_snapshot
            if isinstance(application.creator_profile_snapshot, dict)
            else {}
        )
        result[_bd_name(outbox)] = {
            "schema_version": snapshot.get("schema_version"),
            "sections": sorted(
                key
                for key in snapshot
                if key not in {"schema_version"} and isinstance(snapshot[key], dict)
            ),
            "source_type": application.creator_profile_source_type,
            "observed_at_recorded": application.creator_profile_observed_at is not None,
        }
    return result


def _has_profile(application) -> bool:
    snapshot = application.creator_profile_snapshot
    return isinstance(snapshot, dict) and snapshot.get("schema_version") == 2


if __name__ == "__main__":
    asyncio.run(main())
