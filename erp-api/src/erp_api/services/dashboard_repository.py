from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import BigInteger, case, cast, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.order import Order
from erp_api.models.order_line import OrderLine
from erp_api.models.order_recipient import OrderRecipient
from erp_api.models.shop import Shop
from erp_api.services.dashboard_ranges import TimeWindow

EXCLUDED_SALES_STATUSES = ("cancelled", "unpaid")


@dataclass(frozen=True)
class DashboardFilters:
    platform: str | None
    site: str | None
    shop_id: UUID | None
    currency: str


class DashboardRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def filter_options(
        self, tenant_id: UUID
    ) -> dict[str, list[dict[str, object]] | list[str]]:
        async for session in self._database.session(tenant_id):
            shop_rows = (
                await session.execute(
                    select(
                        Shop.id,
                        Shop.shop_name,
                        Shop.platform,
                        Shop.region,
                        Shop.currency,
                        Shop.timezone,
                    )
                    .where(Shop.status == "active")
                    .order_by(Shop.platform, Shop.region, Shop.shop_name)
                )
            ).all()
            order_currencies = (
                await session.scalars(
                    select(Order.currency)
                    .join(Shop, Shop.id == Order.shop_id)
                    .where(Shop.status == "active")
                    .distinct()
                    .order_by(Order.currency)
                )
            ).all()
            shops = [
                {
                    "id": str(row.id),
                    "name": row.shop_name,
                    "platform": row.platform,
                    "site": row.region,
                    "currency": row.currency,
                    "timezone": row.timezone,
                }
                for row in shop_rows
            ]
            currencies = sorted({currency for currency in order_currencies if currency})
            currencies.extend(
                sorted(
                    {
                        row.currency
                        for row in shop_rows
                        if row.currency and row.currency not in currencies
                    }
                )
            )
            return {
                "platforms": sorted(
                    {row.platform for row in shop_rows if row.platform}
                ),
                "sites": sorted({row.region for row in shop_rows if row.region}),
                "shops": shops,
                "currencies": currencies or ["USD"],
            }
        return {"platforms": [], "sites": [], "shops": [], "currencies": ["USD"]}

    async def summary(
        self, tenant_id: UUID, filters: DashboardFilters, window: TimeWindow
    ) -> dict[str, int]:
        conditions = self._conditions(filters, window)
        sale_conditions = [*conditions, Order.status.not_in(EXCLUDED_SALES_STATUSES)]
        async for session in self._database.session(tenant_id):
            order_row = (
                await session.execute(
                    select(
                        func.count(Order.id),
                        func.coalesce(func.sum(Order.total_amount_minor), 0),
                    )
                    .join(Shop, Shop.id == Order.shop_id)
                    .where(*sale_conditions)
                )
            ).one()
            sales_volume = await session.scalar(
                select(func.coalesce(func.sum(OrderLine.quantity), 0))
                .join(Order, Order.id == OrderLine.order_id)
                .join(Shop, Shop.id == Order.shop_id)
                .where(*sale_conditions)
            )
            cancelled = await session.scalar(
                select(func.count(Order.id))
                .join(Shop, Shop.id == Order.shop_id)
                .where(*conditions, Order.status == "cancelled")
            )
            volume = int(sales_volume or 0)
            amount = int(order_row[1] or 0)
            return {
                "salesVolume": volume,
                "orderCount": int(order_row[0] or 0),
                "salesAmountMinor": amount,
                "netSalesAmountMinor": amount,
                "averageItemPriceMinor": round(amount / volume) if volume else 0,
                "cancelledOrderCount": int(cancelled or 0),
            }
        return self._empty_summary()

    async def trend(
        self,
        tenant_id: UUID,
        filters: DashboardFilters,
        window: TimeWindow,
        timezone: str,
    ) -> list[dict[str, object]]:
        conditions = [
            *self._conditions(filters, window),
            Order.status.not_in(EXCLUDED_SALES_STATUSES),
        ]
        local_day = func.date_trunc(
            "day", func.timezone(timezone, Order.placed_at)
        ).label("local_day")
        per_order = (
            select(
                Order.id.label("order_id"),
                local_day,
                Order.total_amount_minor.label("amount"),
                func.coalesce(func.sum(OrderLine.quantity), 0).label("volume"),
            )
            .join(Shop, Shop.id == Order.shop_id)
            .outerjoin(OrderLine, OrderLine.order_id == Order.id)
            .where(*conditions)
            .group_by(Order.id, local_day)
            .subquery()
        )
        statement = (
            select(
                per_order.c.local_day,
                func.count(per_order.c.order_id),
                func.coalesce(func.sum(per_order.c.volume), 0),
                func.coalesce(func.sum(per_order.c.amount), 0),
            )
            .group_by(per_order.c.local_day)
            .order_by(per_order.c.local_day)
        )
        async for session in self._database.session(tenant_id):
            rows = (await session.execute(statement)).all()
            return [
                {
                    "date": row[0].date().isoformat(),
                    "orderCount": int(row[1]),
                    "salesVolume": int(row[2]),
                    "salesAmountMinor": int(row[3]),
                    "netSalesAmountMinor": int(row[3]),
                }
                for row in rows
            ]
        return []

    async def sales_distribution(
        self, tenant_id: UUID, filters: DashboardFilters, window: TimeWindow
    ) -> list[dict[str, object]]:
        conditions = [
            *self._conditions(filters, window),
            Order.status.not_in(EXCLUDED_SALES_STATUSES),
        ]
        return await self._grouped_distribution(tenant_id, conditions, Shop.platform)

    async def order_distribution(
        self, tenant_id: UUID, filters: DashboardFilters, window: TimeWindow
    ) -> list[dict[str, object]]:
        conditions = [
            *self._conditions(filters, window),
            Order.status.not_in(EXCLUDED_SALES_STATUSES),
        ]
        country = func.coalesce(OrderRecipient.country_code, "UNKNOWN")
        return await self._grouped_distribution(
            tenant_id, conditions, country, join_recipient=True
        )

    async def fulfilment(
        self, tenant_id: UUID, filters: DashboardFilters
    ) -> list[dict[str, object]]:
        window = TimeWindow(
            start=datetime(1970, 1, 1, tzinfo=UTC),
            end=datetime(2999, 1, 1, tzinfo=UTC),
        )
        conditions = self._conditions(filters, window)
        groups = [
            ("待发货", ["awaiting_shipment"]),
            ("待审核", ["on_hold"]),
            ("待处理", ["awaiting_shipment"]),
            ("物流中", ["shipping", "partially_shipped"]),
            ("待揽收", ["awaiting_collection"]),
        ]
        async for session in self._database.session(tenant_id):
            result = []
            for label, statuses in groups:
                count = await session.scalar(
                    select(func.count(Order.id))
                    .join(Shop, Shop.id == Order.shop_id)
                    .where(*conditions, Order.status.in_(statuses))
                )
                result.append({"label": label, "value": int(count or 0)})
            return result
        return []

    async def product_performance(
        self, tenant_id: UUID, filters: DashboardFilters, window: TimeWindow
    ) -> list[dict[str, object]]:
        conditions = [
            *self._conditions(filters, window),
            Order.status.not_in(EXCLUDED_SALES_STATUSES),
        ]
        gross_amount = case(
            (
                OrderLine.sale_unit_price_minor > 0,
                OrderLine.sale_unit_price_minor * OrderLine.quantity,
            ),
            (
                OrderLine.original_unit_price_minor > 0,
                OrderLine.original_unit_price_minor * OrderLine.quantity,
            ),
            else_=0,
        )
        allocation_weight = case(
            (gross_amount > 0, gross_amount),
            else_=OrderLine.quantity,
        )
        weighted_lines = (
            select(
                OrderLine.product_name.label("name"),
                OrderLine.seller_sku.label("sku"),
                OrderLine.platform_product_id.label("product_id"),
                Shop.platform.label("platform"),
                Shop.shop_name.label("store"),
                OrderLine.image_url.label("image_url"),
                OrderLine.quantity.label("quantity"),
                gross_amount.label("gross_amount"),
                Order.total_amount_minor.label("paid_amount"),
                allocation_weight.label("allocation_weight"),
                func.sum(allocation_weight)
                .over(partition_by=Order.id)
                .label("order_weight"),
            )
            .join(Order, Order.id == OrderLine.order_id)
            .join(Shop, Shop.id == Order.shop_id)
            .where(*conditions)
            .subquery()
        )
        allocated_paid = cast(
            weighted_lines.c.paid_amount
            * weighted_lines.c.allocation_weight
            / func.nullif(weighted_lines.c.order_weight, 0),
            BigInteger,
        )
        statement = (
            select(
                weighted_lines.c.name,
                weighted_lines.c.sku,
                weighted_lines.c.product_id,
                weighted_lines.c.platform,
                weighted_lines.c.store,
                func.max(weighted_lines.c.image_url).label("image_url"),
                func.sum(weighted_lines.c.quantity).label("volume"),
                func.sum(weighted_lines.c.gross_amount).label("gross_amount"),
                func.sum(allocated_paid).label("net_amount"),
            )
            .group_by(
                weighted_lines.c.name,
                weighted_lines.c.sku,
                weighted_lines.c.product_id,
                weighted_lines.c.platform,
                weighted_lines.c.store,
            )
            .order_by(func.sum(weighted_lines.c.gross_amount).desc())
            .limit(10)
        )
        async for session in self._database.session(tenant_id):
            rows = (await session.execute(statement)).all()
            return [
                {
                    "name": row[0],
                    "sku": row[1] or "未匹配",
                    "productId": row[2] or "未匹配",
                    "platform": row[3],
                    "store": row[4],
                    "imageUrl": row[5],
                    "salesVolume": int(row[6] or 0),
                    "salesAmountMinor": int(row[7] or 0),
                    "netSalesAmountMinor": int(row[8] or 0),
                }
                for row in rows
            ]
        return []

    async def _grouped_distribution(
        self, tenant_id, conditions, group_column, *, join_recipient=False
    ):
        line_volume = (
            select(OrderLine.order_id, func.sum(OrderLine.quantity).label("volume"))
            .group_by(OrderLine.order_id)
            .subquery()
        )
        statement = (
            select(
                group_column.label("key"),
                func.count(Order.id),
                func.coalesce(func.sum(line_volume.c.volume), 0),
                func.coalesce(func.sum(Order.total_amount_minor), 0),
            )
            .join(Shop, Shop.id == Order.shop_id)
            .outerjoin(line_volume, line_volume.c.order_id == Order.id)
        )
        if join_recipient:
            statement = statement.outerjoin(
                OrderRecipient, OrderRecipient.order_id == Order.id
            )
        statement = (
            statement.where(*conditions)
            .group_by(group_column)
            .order_by(func.count(Order.id).desc())
        )
        async for session in self._database.session(tenant_id):
            rows = (await session.execute(statement)).all()
            return [
                {
                    "key": str(row[0]),
                    "orderCount": int(row[1]),
                    "salesVolume": int(row[2]),
                    "salesAmountMinor": int(row[3]),
                }
                for row in rows
            ]
        return []

    @staticmethod
    def _conditions(filters: DashboardFilters, window: TimeWindow) -> list[object]:
        conditions: list[object] = [
            Order.placed_at >= window.start,
            Order.placed_at < window.end,
            Order.currency == filters.currency,
            Shop.status == "active",
        ]
        if filters.platform:
            conditions.append(Shop.platform == filters.platform)
        if filters.site:
            conditions.append(Shop.region == filters.site)
        if filters.shop_id:
            conditions.append(Shop.id == filters.shop_id)
        return conditions

    @staticmethod
    def _empty_summary() -> dict[str, int]:
        return {
            "salesVolume": 0,
            "orderCount": 0,
            "salesAmountMinor": 0,
            "netSalesAmountMinor": 0,
            "averageItemPriceMinor": 0,
            "cancelledOrderCount": 0,
        }
