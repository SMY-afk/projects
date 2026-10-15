from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.services.sample_application_group_projection import (
    application_group_projections,
    expand_application_group_projection,
    stabilize_application_group_projection,
)
from erp_api.services.sample_group_projection_detach import detach_obsolete_group_links


@dataclass(frozen=True)
class SampleApplicationTimeEnrichmentResult:
    matched_count: int
    updated_count: int
    missing_time_count: int
    application_ids: frozenset[UUID]
    obsolete_platform_application_ids: frozenset[str] = frozenset()
    grouped_product_updates: tuple[tuple[str, tuple[str, ...]], ...] = ()


class SampleApplicationTimeEnrichmentService:
    """Add real TikTok UI create times to official seller API records."""
    def __init__(self, database: Database) -> None:
        self._database = database

    async def enrich(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        applications: Sequence[Mapping[str, object]],
        observed_at: datetime,
        request_id: str | None,
    ) -> SampleApplicationTimeEnrichmentResult:
        times, missing = application_times(applications)
        invitation_sources = application_invitation_sources(applications)
        group_projections = application_group_projections(applications)
        application_ids = set(times) | set(invitation_sources)
        application_ids.update(
            source_id
            for projection in group_projections
            for source_id in projection["source_item_ids"]
        )
        if not application_ids:
            return SampleApplicationTimeEnrichmentResult(0, 0, missing, frozenset())
        async with self._database.system_session_factory() as session:
            rows = (
                await session.scalars(
                    select(SampleApplication).where(
                        SampleApplication.tenant_id == tenant_id,
                        SampleApplication.shop_id == shop_id,
                        SampleApplication.source_type == "official_api",
                        SampleApplication.platform_application_id.in_(
                            tuple(application_ids)
                        ),
                    )
                )
            ).all()
            creator_ids = {
                creator_id
                for application in rows
                if isinstance(
                    creator_id := getattr(application, "creator_open_id", None), str
                )
                and creator_id
            }
            if creator_ids:
                creator_rows = (
                    await session.scalars(
                        select(SampleApplication).where(
                            SampleApplication.tenant_id == tenant_id,
                            SampleApplication.shop_id == shop_id,
                            SampleApplication.source_type == "official_api",
                            SampleApplication.creator_open_id.in_(tuple(creator_ids)),
                        )
                    )
                ).all()
                rows = list({application.id: application for application in (*rows, *creator_rows)}.values())
            updated_ids = set()
            projection_sync_ids: set[UUID] = set()
            obsolete_platform_ids: set[str] = set()
            grouped_product_updates = []
            rows_by_platform_id = {
                application.platform_application_id: application
                for application in rows
            }
            for application in rows:
                platform_id = application.platform_application_id
                if platform_id in times:
                    applied_at = datetime.fromtimestamp(times[platform_id], UTC)
                    if application.tiktok_applied_at != applied_at:
                        before = application.tiktok_applied_at
                        application.tiktok_applied_at = applied_at
                        session.add(
                            SampleApplicationEvent(
                                tenant_id=tenant_id,
                                shop_id=shop_id,
                                sample_application_id=application.id,
                                event_type="tiktok_application_time_enriched",
                                event_source="tiktok_ziniao_cdp",
                                external_event_id=(
                                    f"{request_id}:{platform_id}:time"
                                    if request_id
                                    else None
                                ),
                                before_data={
                                    "tiktok_applied_at": (
                                        before.isoformat() if before else None
                                    )
                                },
                                after_data={
                                    "tiktok_applied_at": applied_at.isoformat()
                                },
                                occurred_at=observed_at.astimezone(UTC),
                            )
                        )
                        updated_ids.add(application.id)
                if platform_id in invitation_sources:
                    source_type, proactive = invitation_sources[platform_id]
                    raw_payload = (
                        dict(application.raw_payload)
                        if isinstance(application.raw_payload, dict)
                        else {}
                    )
                    before_source = raw_payload.get("application_source_type")
                    before_proactive = raw_payload.get("is_proactive_invitation")
                    if (before_source, before_proactive) != (source_type, proactive):
                        raw_payload["application_source_type"] = source_type
                        raw_payload["is_proactive_invitation"] = proactive
                        application.raw_payload = raw_payload
                        session.add(
                            SampleApplicationEvent(
                                tenant_id=tenant_id,
                                shop_id=shop_id,
                                sample_application_id=application.id,
                                event_type="sample_invitation_source_enriched",
                                event_source="tiktok_ziniao_cdp",
                                external_event_id=(
                                    f"{request_id}:{platform_id}:invitation-source"
                                    if request_id
                                    else None
                                ),
                                before_data={
                                    "application_source_type": before_source,
                                    "is_proactive_invitation": before_proactive,
                                },
                                after_data={
                                    "application_source_type": source_type,
                                    "is_proactive_invitation": proactive,
                                },
                                occurred_at=observed_at.astimezone(UTC),
                            )
                        )
                        updated_ids.add(application.id)
            for projection in group_projections:
                parent = rows_by_platform_id.get(projection["parent_application_id"])
                if parent is None:
                    continue
                projection_sync_ids.add(parent.id)
                members = [
                    rows_by_platform_id[source_id]
                    for source_id in projection["source_item_ids"]
                    if source_id in rows_by_platform_id
                ]
                updated_ids.update(detach_obsolete_group_links(
                    rows, projection, session, tenant_id=tenant_id, shop_id=shop_id,
                    observed_at=observed_at,
                ))
                projection = expand_application_group_projection(projection, members)
                projection = stabilize_application_group_projection(projection, parent.raw_payload)
                obsolete_platform_ids.update(
                    source_id
                    for source_id in projection["source_item_ids"]
                    if source_id != projection["parent_application_id"]
                )
                group_changed = False
                for source_id in projection["source_item_ids"]:
                    member = rows_by_platform_id.get(source_id)
                    if member is None:
                        continue
                    is_parent = member is parent
                    member_payload = (
                        dict(member.raw_payload)
                        if isinstance(member.raw_payload, dict)
                        else {}
                    )
                    member_projection = dict(projection)
                    member_payload["ziniao_group_projection"] = member_projection
                    if member.raw_payload != member_payload:
                        member.raw_payload = member_payload
                        group_changed = True
                        updated_ids.add(member.id)
                    if member.is_current_projection is not is_parent:
                        member.is_current_projection = is_parent
                        group_changed = True
                        updated_ids.add(member.id)
                for field_name in (
                    "platform_status",
                    "product_id",
                    "product_title",
                    "sku_id",
                    "sku_name",
                    "product_image_urls",
                ):
                    value = projection[field_name]
                    if getattr(parent, field_name) != value:
                        setattr(parent, field_name, value)
                        group_changed = True
                        updated_ids.add(parent.id)
                if group_changed:
                    grouped_product_updates.append(
                        (parent.platform_application_id, tuple(projection["product_ids"]))
                    )
                    session.add(
                        SampleApplicationEvent(
                            tenant_id=tenant_id,
                            shop_id=shop_id,
                            sample_application_id=parent.id,
                            event_type="sample_group_projection_reconciled",
                            event_source="tiktok_ziniao_cdp",
                            external_event_id=(
                                f"{request_id}:{parent.platform_application_id}:group"
                                if request_id
                                else None
                            ),
                            before_data=None,
                            after_data={
                                "source_item_ids": projection["source_item_ids"],
                                "product_ids": projection["product_ids"],
                            },
                            occurred_at=observed_at.astimezone(UTC),
                        )
                    )
            await session.commit()
        return SampleApplicationTimeEnrichmentResult(
            matched_count=len(rows),
            updated_count=len(updated_ids),
            missing_time_count=missing,
            application_ids=frozenset(updated_ids | projection_sync_ids),
            obsolete_platform_application_ids=frozenset(obsolete_platform_ids),
            grouped_product_updates=tuple(grouped_product_updates),
        )


def application_times(
    applications: Sequence[Mapping[str, object]],
) -> tuple[dict[str, int], int]:
    result: dict[str, int] = {}
    missing = 0
    for application in applications:
        products = application.get("products")
        if not isinstance(products, list):
            products = []
        for item in products:
            if not isinstance(item, Mapping):
                continue
            application_id = item.get("application_id")
            applied_at = item.get("application_time")
            if isinstance(application_id, str) and isinstance(applied_at, int):
                result[application_id] = applied_at
            elif isinstance(application_id, str):
                missing += 1
    return result, missing


def application_invitation_sources(
    applications: Sequence[Mapping[str, object]],
) -> dict[str, tuple[int, bool]]:
    result: dict[str, tuple[int, bool]] = {}
    for application in applications:
        products = application.get("products")
        if not isinstance(products, list):
            continue
        for item in products:
            if not isinstance(item, Mapping):
                continue
            application_id = item.get("application_id")
            source_type = item.get("application_source_type")
            proactive = item.get("is_proactive_invitation")
            if (
                isinstance(application_id, str)
                and isinstance(source_type, int)
                and not isinstance(source_type, bool)
                and isinstance(proactive, bool)
            ):
                result[application_id] = (source_type, proactive)
    return result
