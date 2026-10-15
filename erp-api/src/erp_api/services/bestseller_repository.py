from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.bestseller_snapshot import BestsellerEntry, BestsellerSnapshot
from erp_api.services.tiktok_bestseller_client import (
    BestsellerAuthorType,
    BestsellerTimeSlot,
)
from erp_api.services.tiktok_bestseller_schemas import (
    BestsellerCurrency,
    BestsellerEntityType,
    TikTokBestsellerEntry,
    TikTokBestsellerPage,
)

NO_AUTHOR_TYPE = "NONE"


@dataclass(frozen=True)
class BestsellerSnapshotQuery:
    shop_id: UUID
    entity_type: BestsellerEntityType
    reference_date: date
    time_slot: BestsellerTimeSlot
    currency: BestsellerCurrency
    author_type: BestsellerAuthorType | None = None

    def normalized_author_type(self) -> str:
        allowed = {"ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"}
        if self.entity_type == "creator":
            if self.author_type not in allowed:
                raise ValueError("Creator snapshots require a valid author_type.")
            return self.author_type
        if self.author_type is not None:
            raise ValueError("author_type is only valid for creator snapshots.")
        return NO_AUTHOR_TYPE


class BestsellerRepository:
    def __init__(self, database: Database, *, raw_payload_ttl_days: int = 30) -> None:
        if raw_payload_ttl_days < 1:
            raise ValueError("raw_payload_ttl_days must be positive.")
        self._database = database
        self._raw_payload_ttl = timedelta(days=raw_payload_ttl_days)

    async def replace_snapshot(
        self,
        tenant_id: UUID,
        query: BestsellerSnapshotQuery,
        page: TikTokBestsellerPage,
    ) -> UUID:
        author_type = self._validate(query, page)
        request_id = page.platform_request_id.strip()
        refreshed_at = datetime.now(UTC)
        entry_rows = self._entry_rows(
            tenant_id,
            page.entries,
            query.currency,
            raw_payload_expires_at=refreshed_at + self._raw_payload_ttl,
        )
        snapshot_insert = insert(BestsellerSnapshot).values(
            tenant_id=tenant_id,
            shop_id=query.shop_id,
            entity_type=query.entity_type,
            reference_date=query.reference_date,
            time_slot=query.time_slot,
            currency=query.currency,
            author_type=author_type,
            platform_request_id=request_id,
            entry_count=len(entry_rows),
            is_stale=False,
            last_error_category=None,
            last_error_at=None,
            refreshed_at=refreshed_at,
        )
        snapshot_statement = snapshot_insert.on_conflict_do_update(
            constraint="uq_bestseller_snapshots_query",
            set_={
                "platform_request_id": snapshot_insert.excluded.platform_request_id,
                "entry_count": snapshot_insert.excluded.entry_count,
                "is_stale": False,
                "last_error_category": None,
                "last_error_at": None,
                "refreshed_at": refreshed_at,
            },
        ).returning(BestsellerSnapshot.id)

        async for session in self._database.session(tenant_id):
            snapshot_id = await session.scalar(snapshot_statement)
            if snapshot_id is None:
                raise RuntimeError("Bestseller snapshot upsert returned no identifier.")
            await session.execute(
                delete(BestsellerEntry).where(
                    BestsellerEntry.snapshot_id == snapshot_id
                )
            )
            if entry_rows:
                await session.execute(
                    insert(BestsellerEntry).values(
                        [
                            {
                                **row,
                                "snapshot_id": snapshot_id,
                            }
                            for row in entry_rows
                        ]
                    )
                )
            await session.commit()
            return snapshot_id
        raise RuntimeError("Tenant database session was not created.")

    async def mark_snapshot_stale(
        self,
        tenant_id: UUID,
        query: BestsellerSnapshotQuery,
        error_category: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        author_type = query.normalized_author_type()
        if not error_category or len(error_category) > 32:
            raise ValueError("error_category is required and must be bounded.")
        failed_at = self._utc(now) if now else datetime.now(UTC)
        statement = (
            update(BestsellerSnapshot)
            .where(
                BestsellerSnapshot.tenant_id == tenant_id,
                BestsellerSnapshot.shop_id == query.shop_id,
                BestsellerSnapshot.entity_type == query.entity_type,
                BestsellerSnapshot.reference_date == query.reference_date,
                BestsellerSnapshot.time_slot == query.time_slot,
                BestsellerSnapshot.currency == query.currency,
                BestsellerSnapshot.author_type == author_type,
            )
            .values(
                is_stale=True,
                last_error_category=error_category,
                last_error_at=failed_at,
            )
        )
        async for session in self._database.session(tenant_id):
            result = await session.execute(statement)
            await session.commit()
            return (result.rowcount or 0) == 1
        raise RuntimeError("Tenant database session was not created.")

    async def clear_expired_raw_payloads(
        self, tenant_id: UUID, *, now: datetime | None = None
    ) -> int:
        expires_before = self._utc(now) if now else datetime.now(UTC)
        statement = (
            update(BestsellerEntry)
            .where(
                BestsellerEntry.raw_payload.is_not(None),
                BestsellerEntry.raw_payload_expires_at <= expires_before,
            )
            .values(raw_payload=None, raw_payload_expires_at=None)
        )
        async for session in self._database.session(tenant_id):
            result = await session.execute(statement)
            await session.commit()
            return result.rowcount or 0
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _validate(query: BestsellerSnapshotQuery, page: TikTokBestsellerPage) -> str:
        if query.entity_type not in {"product", "creator", "video", "live"}:
            raise ValueError("entity_type is invalid.")
        if not isinstance(query.reference_date, date) or isinstance(
            query.reference_date, datetime
        ):
            raise TypeError("reference_date must be a date.")
        if query.time_slot not in {"1D", "7D", "30D"}:
            raise ValueError("time_slot is invalid.")
        if query.currency not in {"USD", "LOCAL"}:
            raise ValueError("currency is invalid.")
        request_id = page.platform_request_id
        if not request_id or not request_id.strip() or len(request_id.strip()) > 128:
            raise ValueError("platform_request_id is required and must be bounded.")
        if len(page.entries) > 100:
            raise ValueError("Bestseller snapshots cannot exceed Top 100.")
        ranks = [entry.rank for entry in page.entries]
        external_ids = [entry.external_id for entry in page.entries]
        if len(ranks) != len(set(ranks)):
            raise ValueError("Bestseller snapshot contains a duplicate rank.")
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("Bestseller snapshot contains a duplicate external_id.")
        if any(entry.entity_type != query.entity_type for entry in page.entries):
            raise ValueError("Entry entity_type does not match the snapshot query.")
        if any(entry.gmv.currency_context != query.currency for entry in page.entries):
            raise ValueError("Entry currency does not match the snapshot query.")
        return query.normalized_author_type()

    @staticmethod
    def _entry_rows(
        tenant_id: UUID,
        entries: list[TikTokBestsellerEntry],
        currency: BestsellerCurrency,
        *,
        raw_payload_expires_at: datetime,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for entry in entries:
            if not entry.external_id or len(entry.external_id) > 128:
                raise ValueError("Entry external_id is required and must be bounded.")
            if (
                not isinstance(entry.rank, int)
                or isinstance(entry.rank, bool)
                or entry.rank < 1
                or entry.rank > 100
            ):
                raise ValueError("Entry rank must be between 1 and 100.")
            if not entry.gmv.raw or entry.gmv.computable is not False:
                raise ValueError("GMV range must remain raw and non-computable.")
            try:
                json.dumps(entry.extensions)
                json.dumps(entry.raw_payload)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Entry extensions and raw_payload must be JSON serializable."
                ) from error
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "external_id": entry.external_id,
                    "rank": entry.rank,
                    "display_name": entry.display_name,
                    "gmv_range_raw": entry.gmv.raw,
                    "gmv_currency_context": currency,
                    "extensions": dict(entry.extensions),
                    "raw_payload": dict(entry.raw_payload)
                    if entry.raw_payload
                    else None,
                    "raw_payload_expires_at": raw_payload_expires_at
                    if entry.raw_payload
                    else None,
                }
            )
        return rows

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now must include a UTC offset.")
        return value.astimezone(UTC)
