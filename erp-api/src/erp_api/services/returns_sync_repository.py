from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.order import Order
from erp_api.models.return_request import ReturnRequest, ReturnRequestItem
from erp_api.services.tiktok_return_schemas import TikTokReturn


@dataclass(frozen=True)
class ReturnSyncPageResult:
    fetched_count: int
    upserted_count: int
    unmatched_order_count: int
    unmatched_line_count: int


class ReturnsSyncRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_page(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: list[TikTokReturn],
    ) -> ReturnSyncPageResult:
        if not records:
            return ReturnSyncPageResult(0, 0, 0, 0)
        order_ids = {record.platform_order_id for record in records}
        return_ids = {record.platform_return_id for record in records}
        async for session in self._database.session(tenant_id):
            orders = (
                await session.scalars(
                    select(Order)
                    .options(selectinload(Order.lines))
                    .where(
                        Order.shop_id == shop_id,
                        Order.platform_order_id.in_(order_ids),
                    )
                )
            ).all()
            existing = (
                await session.scalars(
                    select(ReturnRequest)
                    .options(selectinload(ReturnRequest.items))
                    .where(
                        ReturnRequest.shop_id == shop_id,
                        ReturnRequest.platform == "tiktok",
                        ReturnRequest.platform_return_id.in_(return_ids),
                    )
                )
            ).all()
            order_map = {order.platform_order_id: order for order in orders}
            stored_map = {
                item.platform_return_id: item
                for item in existing
                if item.platform_return_id
            }
            upserted = unmatched_orders = unmatched_lines = 0
            for incoming in records:
                order = order_map.get(incoming.platform_order_id)
                if order is None:
                    unmatched_orders += 1
                    continue
                line_map = {line.platform_line_id: line for line in order.lines}
                resolved = [
                    (item, line_map.get(item.platform_order_line_id))
                    for item in incoming.lines
                ]
                if not resolved or any(line is None for _, line in resolved):
                    unmatched_lines += 1
                    continue
                stored = stored_map.get(incoming.platform_return_id)
                if (
                    stored is not None
                    and stored.platform_updated_at is not None
                    and stored.platform_updated_at > incoming.updated_at
                ):
                    continue
                if stored is None:
                    stored = ReturnRequest(
                        tenant_id=tenant_id,
                        request_number=f"TT-{incoming.platform_return_id}"[:40],
                        order_id=order.id,
                        shop_id=shop_id,
                        source="platform",
                        platform="tiktok",
                        platform_return_id=incoming.platform_return_id,
                        created_by_user_id=None,
                        created_at=incoming.created_at,
                    )
                    session.add(stored)
                    stored_map[incoming.platform_return_id] = stored
                else:
                    stored.items.clear()
                    await session.flush()
                self._assign(stored, incoming)
                stored.items.extend(
                    ReturnRequestItem(
                        tenant_id=tenant_id,
                        order_line_id=line.id,
                        platform_return_line_id=item.platform_return_line_id,
                        requested_quantity=item.requested_quantity,
                        reason_code=incoming.reason_code,
                    )
                    for item, line in resolved
                    if line is not None
                )
                upserted += 1
            await session.commit()
            return ReturnSyncPageResult(
                fetched_count=len(records),
                upserted_count=upserted,
                unmatched_order_count=unmatched_orders,
                unmatched_line_count=unmatched_lines,
            )
        raise RuntimeError("Tenant database session was not created.")

    @staticmethod
    def _assign(stored: ReturnRequest, incoming: TikTokReturn) -> None:
        stored.request_type = incoming.request_type
        stored.status = incoming.status
        stored.reason_code = incoming.reason_code
        stored.platform_status = incoming.platform_status
        stored.platform_reason_text = incoming.reason_text
        stored.platform_created_at = incoming.created_at
        stored.platform_updated_at = incoming.updated_at
        stored.refund_currency = incoming.refund_currency
        stored.refund_amount_minor = incoming.refund_amount_minor
        stored.raw_payload = incoming.raw_payload
