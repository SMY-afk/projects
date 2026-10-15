from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy import delete, exists, select

from erp_api.models.order_line import OrderLine
from erp_api.models.return_request import ReturnRequestItem
from erp_api.services.tiktok_order_schemas import TikTokOrderLine

ResolveSku = Callable[
    [object, UUID, TikTokOrderLine],
    Awaitable[tuple[UUID | None, UUID | None]],
]


async def sync_order_lines(
    session,
    *,
    tenant_id: UUID,
    shop_id: UUID,
    order_id: UUID,
    incoming_lines: list[TikTokOrderLine],
    resolve_sku: ResolveSku,
) -> None:
    existing = (
        await session.scalars(select(OrderLine).where(OrderLine.order_id == order_id))
    ).all()
    by_platform_id = {line.platform_line_id: line for line in existing}
    incoming_ids = {_bounded(line.platform_line_id, 128) for line in incoming_lines}

    for incoming in incoming_lines:
        platform_line_id = _bounded(incoming.platform_line_id, 128)
        stored = by_platform_id.get(platform_line_id)
        product_id, sku_id = await resolve_sku(session, shop_id, incoming)
        if stored is None:
            stored = OrderLine(
                tenant_id=tenant_id,
                order_id=order_id,
                platform_line_id=platform_line_id,
            )
            session.add(stored)
        stored.product_id = product_id
        stored.product_sku_id = sku_id
        stored.platform_product_id = _bounded_optional(
            incoming.platform_product_id, 128
        )
        stored.platform_sku_id = _bounded_optional(incoming.platform_sku_id, 128)
        stored.seller_sku = _bounded_optional(incoming.seller_sku, 128)
        stored.product_name = _bounded(incoming.product_name, 300)
        stored.sku_name = _bounded_optional(incoming.sku_name, 300)
        stored.image_url = _bounded_optional(incoming.image_url, 1000)
        stored.quantity = incoming.quantity
        stored.original_unit_price_minor = incoming.original_unit_price_minor
        stored.sale_unit_price_minor = incoming.sale_unit_price_minor
        stored.discount_amount_minor = incoming.discount_amount_minor
        stored.line_total_amount_minor = incoming.line_total_amount_minor

    referenced = exists(
        select(ReturnRequestItem.id).where(
            ReturnRequestItem.order_line_id == OrderLine.id
        )
    )
    await session.execute(
        delete(OrderLine).where(
            OrderLine.order_id == order_id,
            OrderLine.platform_line_id.not_in(incoming_ids),
            ~referenced,
        )
    )


def _bounded(value: str, limit: int) -> str:
    return value[:limit]


def _bounded_optional(value: str | None, limit: int) -> str | None:
    return _bounded(value, limit) if value else None
