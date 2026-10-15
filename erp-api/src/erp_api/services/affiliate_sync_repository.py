from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.affiliate_sync_state import AffiliateSyncState
from erp_api.models.shop import Shop
from erp_api.services.order_evidence_repository import (
    EvidenceIngestResult,
    OrderEvidenceRepository,
)


class AffiliateSyncError(ValueError):
    """Raised when captured Affiliate data cannot be persisted safely."""


@dataclass(frozen=True)
class AffiliateSyncResult:
    received_count: int
    unique_count: int
    upserted_count: int
    evidence_count: int = 0
    attribution_count: int = 0
    unmatched_count: int = 0


class AffiliateSyncRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._evidence_repository = OrderEvidenceRepository()

    async def resolve_shop_id(
        self,
        tenant_id: UUID,
        platform_shop_id: str,
    ) -> UUID | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(
                select(Shop.id).where(
                    Shop.platform == "tiktok",
                    Shop.platform_shop_id == platform_shop_id,
                )
            )
        raise RuntimeError("Tenant database session was not created.")

    async def bulk_upsert(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
        *,
        next_cursor: str | None,
        has_more: bool,
    ) -> AffiliateSyncResult:
        values = self._normalize_records(tenant_id, shop_id, records)
        async for session in self._database.session(tenant_id):
            upserted_count = 0
            if values:
                result = await session.execute(self._order_upsert(values))
                upserted_count = len(result.scalars().all())
            evidence_result = await self._evidence_repository.ingest_affiliate_records(
                session,
                tenant_id,
                shop_id,
                values,
            )
            await session.execute(
                self._state_upsert(
                    tenant_id,
                    shop_id,
                    next_cursor=next_cursor,
                    has_more=has_more,
                )
            )
            await session.commit()
            return AffiliateSyncResult(
                received_count=len(records),
                unique_count=len(values),
                upserted_count=upserted_count,
                evidence_count=evidence_result.evidence_count,
                attribution_count=evidence_result.attribution_count,
                unmatched_count=evidence_result.unmatched_count,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def mark_failed(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        error: str,
    ) -> None:
        safe_error = error[:2000]
        statement = insert(AffiliateSyncState).values(
            tenant_id=tenant_id,
            shop_id=shop_id,
            has_more=False,
            last_synced_at=func.now(),
            last_error=safe_error,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_affiliate_sync_states_shop",
            set_={
                "last_synced_at": func.now(),
                "last_error": safe_error,
                "updated_at": func.now(),
            },
            where=AffiliateSyncState.tenant_id == statement.excluded.tenant_id,
        )
        async for session in self._database.session(tenant_id):
            await session.execute(statement)
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")

    async def rebuild_evidence(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> EvidenceIngestResult:
        async for session in self._database.session(tenant_id):
            statement = select(AffiliateOrderItem).where(
                AffiliateOrderItem.shop_id == shop_id
            )
            if created_from is not None:
                statement = statement.where(
                    AffiliateOrderItem.order_created_at >= created_from
                )
            if created_to is not None:
                statement = statement.where(
                    AffiliateOrderItem.order_created_at <= created_to
                )
            rows = (await session.scalars(statement)).all()
            result = await self._evidence_repository.ingest_affiliate_records(
                session,
                tenant_id,
                shop_id,
                [_model_record(row) for row in rows],
            )
            await session.commit()
            return result
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _order_upsert(values: list[dict[str, object]]):
        statement = insert(AffiliateOrderItem).values(values)
        excluded = statement.excluded
        return statement.on_conflict_do_update(
            constraint="uq_affiliate_order_items_shop_source_record",
            set_={
                "main_order_id": excluded.main_order_id,
                "creator_id": excluded.creator_id,
                "creator_nickname": excluded.creator_nickname,
                "campaign_id": excluded.campaign_id,
                "product_id": excluded.product_id,
                "product_name": excluded.product_name,
                "image_uri": excluded.image_uri,
                "sku_id": excluded.sku_id,
                "sku_name": excluded.sku_name,
                "order_created_at": excluded.order_created_at,
                "is_cod": excluded.is_cod,
                "is_non_same_shop_order": excluded.is_non_same_shop_order,
                "cos_type": excluded.cos_type,
                "promotion_id": excluded.promotion_id,
                "promotion_type": excluded.promotion_type,
                "content_form": excluded.content_form,
                "commission_base": excluded.commission_base,
                "commission_currency": excluded.commission_currency,
                "commission_rate": excluded.commission_rate,
                "estimated_standard_commission": excluded.estimated_standard_commission,
                "raw_data": excluded.raw_data,
                "updated_at": func.now(),
            },
            where=AffiliateOrderItem.tenant_id == excluded.tenant_id,
        ).returning(AffiliateOrderItem.source_record_key)

    @staticmethod
    def _state_upsert(
        tenant_id: UUID,
        shop_id: UUID,
        *,
        next_cursor: str | None,
        has_more: bool,
    ):
        statement = insert(AffiliateSyncState).values(
            tenant_id=tenant_id,
            shop_id=shop_id,
            next_cursor=next_cursor,
            has_more=has_more,
            last_synced_at=func.now(),
            last_success_at=func.now(),
            last_error=None,
        )
        return statement.on_conflict_do_update(
            constraint="uq_affiliate_sync_states_shop",
            set_={
                "next_cursor": next_cursor,
                "has_more": has_more,
                "last_synced_at": func.now(),
                "last_success_at": func.now(),
                "last_error": None,
                "updated_at": func.now(),
            },
            where=AffiliateSyncState.tenant_id == statement.excluded.tenant_id,
        )

    @staticmethod
    def _normalize_records(
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        unique: dict[str, dict[str, object]] = {}
        for index, record in enumerate(records):
            source_key = record.get("source_record_key")
            if not isinstance(source_key, str) or not source_key:
                raise AffiliateSyncError(
                    f"records[{index}].source_record_key is required"
                )
            unique[source_key] = {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                **record,
            }
        return list(unique.values())


def _model_record(row: AffiliateOrderItem) -> dict[str, object]:
    return {
        "main_order_id": row.main_order_id,
        "creator_id": row.creator_id,
        "campaign_id": row.campaign_id,
        "product_id": row.product_id,
        "sku_id": row.sku_id,
        "order_created_at": row.order_created_at,
        "source_record_key": row.source_record_key,
        "raw_data": row.raw_data,
    }
