from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_order_item import AffiliateOrderItem
from erp_api.models.order import Order


@dataclass(frozen=True)
class AffiliateOrderRecord:
    item: AffiliateOrderItem
    order_id: UUID | None
    order_number: str | None
    order_status: str | None


@dataclass(frozen=True)
class AffiliateOrderPage:
    items: list[AffiliateOrderRecord]
    total: int


@dataclass(frozen=True)
class CreatorStats:
    creator_id: str
    creator_nickname: str | None
    commission_currency: str | None
    order_count: int
    item_count: int
    commission_base: Decimal
    estimated_standard_commission: Decimal
    last_order_at: datetime | None


@dataclass(frozen=True)
class CreatorStatsPage:
    items: list[CreatorStats]
    total: int


class AffiliateRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_orders(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        shop_id: UUID | None = None,
        main_order_id: str | None = None,
        creator_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> AffiliateOrderPage:
        filters = self._filters(
            shop_id=shop_id,
            main_order_id=main_order_id,
            creator_id=creator_id,
            created_from=created_from,
            created_to=created_to,
        )
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    self._order_select()
                    .where(*filters)
                    .order_by(
                        AffiliateOrderItem.order_created_at.desc(),
                        AffiliateOrderItem.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            total = await session.scalar(
                select(func.count()).select_from(AffiliateOrderItem).where(*filters)
            )
            return AffiliateOrderPage(
                items=[self._to_order_record(row) for row in rows],
                total=total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_order(
        self,
        tenant_id: UUID,
        main_order_id: str,
        *,
        shop_id: UUID | None = None,
    ) -> list[AffiliateOrderRecord]:
        filters = self._filters(
            shop_id=shop_id,
            main_order_id=main_order_id,
        )
        async for session in self._database.session(tenant_id):
            rows = (
                await session.execute(
                    self._order_select()
                    .where(*filters)
                    .order_by(
                        AffiliateOrderItem.order_created_at, AffiliateOrderItem.id
                    )
                )
            ).all()
            return [self._to_order_record(row) for row in rows]
        raise RuntimeError("Tenant database session was not created.")

    async def list_creator_stats(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        shop_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> CreatorStatsPage:
        filters = self._filters(
            shop_id=shop_id,
            created_from=created_from,
            created_to=created_to,
        )
        creator_filter = AffiliateOrderItem.creator_id.is_not(None)
        group_columns = (
            AffiliateOrderItem.creator_id,
            AffiliateOrderItem.commission_currency,
        )
        commission_base = func.coalesce(
            func.sum(AffiliateOrderItem.commission_base),
            Decimal(0),
        ).label("commission_base")
        estimated_commission = func.coalesce(
            func.sum(AffiliateOrderItem.estimated_standard_commission),
            Decimal(0),
        ).label("estimated_standard_commission")
        groups = (
            select(*group_columns)
            .where(creator_filter, *filters)
            .group_by(*group_columns)
            .subquery()
        )
        statement = (
            select(
                AffiliateOrderItem.creator_id,
                func.max(AffiliateOrderItem.creator_nickname),
                AffiliateOrderItem.commission_currency,
                func.count(func.distinct(AffiliateOrderItem.main_order_id)),
                func.count(AffiliateOrderItem.id),
                commission_base,
                estimated_commission,
                func.max(AffiliateOrderItem.order_created_at),
            )
            .where(creator_filter, *filters)
            .group_by(*group_columns)
            .order_by(estimated_commission.desc(), AffiliateOrderItem.creator_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        async for session in self._database.session(tenant_id):
            total = await session.scalar(select(func.count()).select_from(groups))
            rows = (await session.execute(statement)).all()
            return CreatorStatsPage(
                items=[
                    CreatorStats(
                        creator_id=row[0],
                        creator_nickname=row[1],
                        commission_currency=row[2],
                        order_count=row[3],
                        item_count=row[4],
                        commission_base=row[5],
                        estimated_standard_commission=row[6],
                        last_order_at=row[7],
                    )
                    for row in rows
                ],
                total=total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _order_select():
        return select(
            AffiliateOrderItem,
            Order.id,
            Order.order_number,
            Order.status,
        ).outerjoin(
            Order,
            and_(
                Order.tenant_id == AffiliateOrderItem.tenant_id,
                Order.shop_id == AffiliateOrderItem.shop_id,
                Order.platform_order_id == AffiliateOrderItem.main_order_id,
            ),
        )

    @staticmethod
    def _to_order_record(row) -> AffiliateOrderRecord:
        return AffiliateOrderRecord(
            item=row[0],
            order_id=row[1],
            order_number=row[2],
            order_status=row[3],
        )

    @staticmethod
    def _filters(
        *,
        shop_id: UUID | None = None,
        main_order_id: str | None = None,
        creator_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[object]:
        filters: list[object] = []
        if shop_id is not None:
            filters.append(AffiliateOrderItem.shop_id == shop_id)
        if main_order_id is not None:
            filters.append(AffiliateOrderItem.main_order_id == main_order_id)
        if creator_id is not None:
            filters.append(AffiliateOrderItem.creator_id == creator_id)
        if created_from is not None:
            filters.append(AffiliateOrderItem.order_created_at >= created_from)
        if created_to is not None:
            filters.append(AffiliateOrderItem.order_created_at < created_to)
        return filters
