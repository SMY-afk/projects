from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_application_mapper import ACTIVE_SAMPLE_STATUSES
from erp_api.services.sample_bd_assignment import BdWorkload


async def load_bd_workloads(
    session,
    *,
    tenant_id,
    shop_id,
    roster: Sequence[BdWorkload],
) -> tuple[BdWorkload, ...]:
    names = {member.name for member in roster}
    statement = (
        select(
            SampleApplicationWorkflow.assigned_bd_name,
            SampleApplicationWorkflow.assigned_at,
            SampleApplication.creator_level,
            SampleApplication.creator_gmv_minor,
            SampleApplication.platform_status,
        )
        .join(
            SampleApplication,
            SampleApplication.id == SampleApplicationWorkflow.sample_application_id,
        )
        .where(
            SampleApplicationWorkflow.tenant_id == tenant_id,
            SampleApplicationWorkflow.shop_id == shop_id,
            SampleApplicationWorkflow.assigned_bd_name.in_(names),
            or_(
                SampleApplication.is_current_projection.is_(True),
                exists().where(
                    SampleNotificationOutbox.sample_application_id
                    == SampleApplication.id,
                    SampleNotificationOutbox.status != "cancelled",
                ),
            ),
        )
    )
    rows = (await session.execute(statement)).all()
    total = Counter(row.assigned_bd_name for row in rows)
    current = Counter(
        row.assigned_bd_name
        for row in rows
        if row.platform_status in ACTIVE_SAMPLE_STATUSES
    )
    by_level: dict[str, Counter[str]] = defaultdict(Counter)
    by_level_gmv: dict[str, Counter[str]] = defaultdict(Counter)
    latest: dict[str, tuple[datetime, str | None]] = {}
    latest_by_level: dict[str, tuple[datetime, str]] = {}
    today = Counter()
    today_start = datetime.now(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    for row in rows:
        if row.creator_level:
            by_level[row.assigned_bd_name][row.creator_level] += 1
            if row.creator_gmv_minor is not None and row.creator_gmv_minor >= 0:
                by_level_gmv[row.assigned_bd_name][row.creator_level] += (
                    row.creator_gmv_minor
                )
            if row.assigned_at and (
                row.creator_level not in latest_by_level
                or row.assigned_at > latest_by_level[row.creator_level][0]
            ):
                latest_by_level[row.creator_level] = (
                    row.assigned_at,
                    row.assigned_bd_name,
                )
        if row.assigned_at and row.assigned_at >= today_start:
            today[row.assigned_bd_name] += 1
        if row.assigned_at and (
            row.assigned_bd_name not in latest
            or row.assigned_at > latest[row.assigned_bd_name][0]
        ):
            latest[row.assigned_bd_name] = (row.assigned_at, row.creator_level)
    return tuple(
        replace(
            member,
            current_pending=current[member.name],
            assigned_today=today[member.name],
            total_assigned=total[member.name],
            level_counts=dict(by_level[member.name]),
            level_gmv_minor_totals=dict(by_level_gmv[member.name]),
            last_assigned_at=(latest.get(member.name) or (None, None))[0],
            last_assigned_level=(latest.get(member.name) or (None, None))[1],
            last_received_levels=frozenset(
                level
                for level, (_assigned_at, bd_name) in latest_by_level.items()
                if bd_name == member.name
            ),
        )
        for member in roster
    )
