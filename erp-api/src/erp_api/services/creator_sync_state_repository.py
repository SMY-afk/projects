from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.creator_sync_state import CreatorSyncState
from erp_api.services.affiliate_avatar_cache_policy import cached_avatar_expression
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_creator_persistence_rows import creator_row
from erp_api.services.creator_sync_state import creator_data_hash, should_sync_creator

CREATOR_UPSERT_BATCH_SIZE = 300


@dataclass(frozen=True)
class CreatorSyncCandidate:
    affiliate_creator_id: UUID
    platform_creator_id: str
    data_hash: str
    record: AffiliateCreatorMetricDTO


@dataclass(frozen=True)
class CreatorSyncOutcome:
    candidate: CreatorSyncCandidate
    succeeded: bool


class CreatorSyncStateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def prepare_candidates(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[AffiliateCreatorMetricDTO],
        *,
        stale_after: timedelta,
        now: datetime | None = None,
    ) -> list[CreatorSyncCandidate]:
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive.")
        current = now or datetime.now(UTC)
        unique = _unique_records(records)
        async for session in self._database.session(tenant_id):
            creator_ids: dict[str, UUID] = {}
            rows = [
                creator_row(tenant_id, shop_id, record) for record in unique.values()
            ]
            for batch in _batches(rows):
                statement = insert(AffiliateCreator).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_affiliate_creators_shop_username",
                    set_={
                        "username": statement.excluded.username,
                        "creator_open_id": func.coalesce(
                            AffiliateCreator.creator_open_id,
                            statement.excluded.creator_open_id,
                        ),
                        "avatar_url": cached_avatar_expression(
                            AffiliateCreator.avatar_url,
                            statement.excluded.avatar_url,
                        ),
                        "source_identifiers": AffiliateCreator.source_identifiers.op(
                            "||"
                        )(statement.excluded.source_identifiers),
                        "last_seen_at": current,
                    },
                ).returning(AffiliateCreator.id, AffiliateCreator.username_normalized)
                result = await session.execute(statement)
                creator_ids.update({row.username_normalized: row.id for row in result})
            states = list(
                await session.scalars(
                    select(CreatorSyncState).where(
                        CreatorSyncState.shop_id == shop_id,
                        CreatorSyncState.affiliate_creator_id.in_(creator_ids.values()),
                    )
                )
            )
            by_creator = {state.affiliate_creator_id: state for state in states}
            candidates = _select_candidates(
                unique,
                creator_ids,
                by_creator,
                stale_before=current - stale_after,
            )
            for batch in _batches(
                [_pending_row(tenant_id, shop_id, item) for item in candidates]
            ):
                statement = insert(CreatorSyncState).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_creator_sync_states_creator",
                    set_={
                        "data_hash": statement.excluded.data_hash,
                        "sync_status": "running",
                        "updated_at": current,
                    },
                )
                await session.execute(statement)
            await session.commit()
            return candidates
        raise RuntimeError("Tenant database session was not created.")

    async def mark_outcomes(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        outcomes: Sequence[CreatorSyncOutcome],
        *,
        now: datetime | None = None,
    ) -> None:
        current = now or datetime.now(UTC)
        succeeded = [outcome.candidate for outcome in outcomes if outcome.succeeded]
        failed = [outcome.candidate for outcome in outcomes if not outcome.succeeded]
        async for session in self._database.session(tenant_id):
            for batch in _batches(
                [_success_row(tenant_id, shop_id, item, current) for item in succeeded]
            ):
                statement = insert(CreatorSyncState).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_creator_sync_states_creator",
                    set_={
                        "last_sync_at": current,
                        "last_video_sync_at": current,
                        "data_hash": statement.excluded.data_hash,
                        "sync_status": "succeeded",
                        "updated_at": current,
                    },
                )
                await session.execute(statement)
            for batch in _batches(
                [_pending_row(tenant_id, shop_id, item) for item in failed]
            ):
                statement = insert(CreatorSyncState).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_creator_sync_states_creator",
                    set_={
                        "data_hash": statement.excluded.data_hash,
                        "sync_status": "failed",
                        "updated_at": current,
                    },
                )
                await session.execute(statement)
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")


def _unique_records(
    records: Sequence[AffiliateCreatorMetricDTO],
) -> dict[str, AffiliateCreatorMetricDTO]:
    return {
        record.username_normalized: record
        for record in records
        if record.source_identifiers.get("tiktok_page_creator_id")
    }


def _select_candidates(unique, creator_ids, states, *, stale_before):
    selected: list[CreatorSyncCandidate] = []
    for username, record in unique.items():
        creator_id = creator_ids.get(username)
        platform_id = record.source_identifiers.get("tiktok_page_creator_id")
        if creator_id is None or not platform_id:
            continue
        data_hash = creator_data_hash(record)
        if should_sync_creator(
            states.get(creator_id), data_hash, stale_before=stale_before
        ):
            selected.append(
                CreatorSyncCandidate(creator_id, platform_id, data_hash, record)
            )
    return selected


def _pending_row(tenant_id, shop_id, candidate):
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "creator_id": candidate.platform_creator_id,
        "affiliate_creator_id": candidate.affiliate_creator_id,
        "data_hash": candidate.data_hash,
        "sync_status": "running",
    }


def _success_row(tenant_id, shop_id, candidate, current):
    return {
        **_pending_row(tenant_id, shop_id, candidate),
        "last_sync_at": current,
        "last_video_sync_at": current,
        "sync_status": "succeeded",
    }


def _batches(rows: list[dict[str, object]]):
    for index in range(0, len(rows), CREATOR_UPSERT_BATCH_SIZE):
        yield rows[index : index + CREATOR_UPSERT_BATCH_SIZE]
