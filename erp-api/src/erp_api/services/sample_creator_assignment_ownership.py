from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.shop import Shop
from erp_api.services.sample_cooperation_parsing import normalize_account_name

CREATOR_ASSIGNMENT_OWNERSHIP_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class CreatorAssignmentOwner:
    creator_id: str
    bd_name: str
    assigned_at: datetime | None
    application_id: UUID
    shop_name: str
    ambiguous: bool = False


@dataclass(frozen=True)
class CreatorAssignmentHistory:
    creator_id: str
    bd_name: str
    assigned_at: datetime | None
    application_id: UUID
    shop_name: str


def assignment_owner_protection_reason(
    owner: CreatorAssignmentOwner,
    *,
    valid_creator_ids: Collection[str],
    ai_invitation_creator_ids: Collection[str],
    now: datetime,
) -> str | None:
    if owner.assigned_at is None:
        return "assignment_owner_time_missing"
    if owner.ambiguous:
        return "assignment_owner_ambiguous"
    assigned_at = (
        owner.assigned_at.astimezone(UTC)
        if owner.assigned_at.tzinfo
        else owner.assigned_at.replace(tzinfo=UTC)
    )
    current = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    if current <= assigned_at + CREATOR_ASSIGNMENT_OWNERSHIP_WINDOW:
        return "creator_assignment_within_7_days"
    creator_id = normalize_account_name(owner.creator_id)
    if creator_id in valid_creator_ids:
        return "creator_assignment_over_7_days_in_valid_table"
    if creator_id in ai_invitation_creator_ids:
        return "creator_assignment_over_7_days_in_ai_table"
    return None


def select_current_assignment_owner(
    history: Sequence[CreatorAssignmentHistory],
) -> CreatorAssignmentOwner:
    if not history:
        raise ValueError("Creator assignment history must not be empty.")
    missing_time = next((item for item in history if item.assigned_at is None), None)
    if missing_time is not None:
        return _owner(missing_time, ambiguous=False)
    ordered = sorted(
        history,
        key=lambda item: (item.assigned_at, str(item.application_id)),
    )
    anchor = ordered[0]
    for item in ordered[1:]:
        if item.assigned_at > anchor.assigned_at + CREATOR_ASSIGNMENT_OWNERSHIP_WINDOW:
            anchor = item
    simultaneous_bds = {
        item.bd_name.strip()
        for item in ordered
        if item.assigned_at == anchor.assigned_at and item.bd_name.strip()
    }
    return _owner(anchor, ambiguous=len(simultaneous_bds) != 1)


def _owner(
    item: CreatorAssignmentHistory,
    *,
    ambiguous: bool,
) -> CreatorAssignmentOwner:
    return CreatorAssignmentOwner(
        creator_id=item.creator_id,
        bd_name=item.bd_name,
        assigned_at=item.assigned_at,
        application_id=item.application_id,
        shop_name=item.shop_name,
        ambiguous=ambiguous,
    )


class SampleCreatorAssignmentOwnershipReader:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def read(
        self,
        tenant_id: UUID,
        creator_ids: Collection[str],
    ) -> dict[str, CreatorAssignmentOwner]:
        requested = frozenset(
            creator_id
            for value in creator_ids
            if (creator_id := normalize_account_name(value))
        )
        if not requested:
            return {}
        statement = (
            select(
                SampleApplication.creator_username,
                SampleApplicationWorkflow.assigned_bd_name,
                SampleApplicationWorkflow.assigned_at,
                SampleApplication.id,
                Shop.shop_name,
            )
            .join(
                SampleApplicationWorkflow,
                SampleApplicationWorkflow.sample_application_id
                == SampleApplication.id,
            )
            .join(Shop, Shop.id == SampleApplication.shop_id)
            .where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplicationWorkflow.assigned_bd_name.is_not(None),
            )
        )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        by_creator: dict[str, list[CreatorAssignmentHistory]] = {}
        for username, bd_name, assigned_at, application_id, shop_name in rows:
            creator_id = normalize_account_name(username)
            if creator_id not in requested or not isinstance(bd_name, str):
                continue
            by_creator.setdefault(creator_id, []).append(
                CreatorAssignmentHistory(
                    creator_id,
                    bd_name,
                    assigned_at,
                    application_id,
                    shop_name,
                )
            )
        return {
            creator_id: select_current_assignment_owner(history)
            for creator_id, history in by_creator.items()
        }
