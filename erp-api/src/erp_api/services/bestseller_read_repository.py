from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select

from erp_api.infrastructure.database import Database
from erp_api.models.bestseller_snapshot import BestsellerEntry, BestsellerSnapshot
from erp_api.services.bestseller_repository import BestsellerSnapshotQuery


@dataclass(frozen=True)
class StoredBestsellerEntry:
    external_id: str
    rank: int
    display_name: str | None
    gmv_range_raw: str
    gmv_currency_context: str
    extensions: dict[str, object]


@dataclass(frozen=True)
class StoredBestsellerSnapshot:
    platform_request_id: str
    entry_count: int
    is_stale: bool
    last_error_category: str | None
    last_error_at: datetime | None
    refreshed_at: datetime
    entries: tuple[StoredBestsellerEntry, ...]


class BestsellerReadRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_snapshot(
        self,
        tenant_id: UUID,
        query: BestsellerSnapshotQuery,
    ) -> StoredBestsellerSnapshot | None:
        author_type = query.normalized_author_type()
        async for session in self._database.session(tenant_id):
            snapshot = (
                await session.execute(
                    select(
                        BestsellerSnapshot.id,
                        BestsellerSnapshot.platform_request_id,
                        BestsellerSnapshot.entry_count,
                        BestsellerSnapshot.is_stale,
                        BestsellerSnapshot.last_error_category,
                        BestsellerSnapshot.last_error_at,
                        BestsellerSnapshot.refreshed_at,
                    ).where(
                        BestsellerSnapshot.tenant_id == tenant_id,
                        BestsellerSnapshot.shop_id == query.shop_id,
                        BestsellerSnapshot.entity_type == query.entity_type,
                        BestsellerSnapshot.reference_date == query.reference_date,
                        BestsellerSnapshot.time_slot == query.time_slot,
                        BestsellerSnapshot.currency == query.currency,
                        BestsellerSnapshot.author_type == author_type,
                    )
                )
            ).one_or_none()
            if snapshot is None:
                return None
            entries = (
                await session.execute(
                    select(
                        BestsellerEntry.external_id,
                        BestsellerEntry.rank,
                        BestsellerEntry.display_name,
                        BestsellerEntry.gmv_range_raw,
                        BestsellerEntry.gmv_currency_context,
                        BestsellerEntry.extensions,
                    )
                    .join(
                        BestsellerSnapshot,
                        and_(
                            BestsellerSnapshot.id == BestsellerEntry.snapshot_id,
                            BestsellerSnapshot.tenant_id == BestsellerEntry.tenant_id,
                        ),
                    )
                    .where(
                        BestsellerEntry.tenant_id == tenant_id,
                        BestsellerSnapshot.tenant_id == tenant_id,
                        BestsellerSnapshot.shop_id == query.shop_id,
                        BestsellerEntry.snapshot_id == snapshot.id,
                    )
                    .order_by(BestsellerEntry.rank)
                )
            ).all()
            return StoredBestsellerSnapshot(
                platform_request_id=snapshot.platform_request_id,
                entry_count=snapshot.entry_count,
                is_stale=snapshot.is_stale,
                last_error_category=snapshot.last_error_category,
                last_error_at=snapshot.last_error_at,
                refreshed_at=snapshot.refreshed_at,
                entries=tuple(
                    StoredBestsellerEntry(
                        external_id=entry.external_id,
                        rank=entry.rank,
                        display_name=entry.display_name,
                        gmv_range_raw=entry.gmv_range_raw,
                        gmv_currency_context=entry.gmv_currency_context,
                        extensions=dict(entry.extensions),
                    )
                    for entry in entries
                ),
            )
        return None
