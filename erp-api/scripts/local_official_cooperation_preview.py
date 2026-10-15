"""Recheck prior cooperation conclusions without overriding business decisions."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.shop import Shop
from erp_api.services.sample_cooperation_rules import (
    CooperationCandidate,
    decide_cooperation,
)


async def require_existing_cooperation_allowed(
    service, database, tenant_id, shop_id, application_id
):
    async with database.system_session_factory() as session:
        app, name = (
            await session.execute(
                select(SampleApplication, Shop.shop_name)
                .join(
                    Shop,
                    Shop.id == SampleApplication.shop_id,
                )
                .where(
                    SampleApplication.tenant_id == tenant_id,
                    SampleApplication.shop_id == shop_id,
                    SampleApplication.platform_application_id == application_id,
                )
            )
        ).one()
    usernames = frozenset({app.creator_username.lstrip("@").casefold()})
    snapshot, owners = await asyncio.gather(
        service._reader.read(creator_ids=usernames),
        service._assignment_ownership.read(tenant_id, usernames),
    )
    now = datetime.now(UTC)
    decision = decide_cooperation(
        CooperationCandidate(
            app.id,
            application_id,
            app.creator_username,
            name,
            app.tiktok_applied_at or app.first_seen_at,
        ),
        replace(snapshot, assignment_owners=owners),
        today=now.astimezone(ZoneInfo("Asia/Shanghai")).date(),
        now=now,
    )
    if decision.blocks_assignment:
        raise RuntimeError(
            "Latest cooperation preview blocks assignment: " + decision.event_type
        )
    print("LATEST_COOPERATION_AND_VALID_CREATORS=allowed", flush=True)
