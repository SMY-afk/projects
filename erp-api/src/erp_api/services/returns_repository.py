from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.order import Order
from erp_api.models.return_request import ReturnRequest, ReturnRequestItem
from erp_api.models.return_rma import ReturnRma
from erp_api.services.returns_domain import (
    ReturnConflictError,
    ReturnItemInput,
    ReturnNotFoundError,
    ReturnValidationError,
    validate_return_items,
)
from erp_api.services.returns_records import return_request_record
from erp_api.services.returns_repository_helpers import (
    create_rma_and_task,
    domain_number,
    find_order,
    reload_request,
    request_select,
    reserved_quantities,
)


@dataclass(frozen=True)
class ReturnRequestPage:
    items: list[dict[str, object]]
    total: int


class ReturnsRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_eligibility(
        self, tenant_id: UUID, order_reference: str
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            order = await find_order(session, order_reference)
            if order is None:
                raise ReturnNotFoundError("Original sales order was not found.")
            reserved = await reserved_quantities(
                session, order.id, [line.id for line in order.lines]
            )
            return {
                "orderId": order.id,
                "orderNumber": order.order_number,
                "shopId": order.shop_id,
                "items": [
                    {
                        "orderLineId": line.id,
                        "sellerSku": line.seller_sku,
                        "productName": line.product_name,
                        "skuName": line.sku_name,
                        "orderedQuantity": line.quantity,
                        "requestedQuantity": reserved.get(line.id, 0),
                        "availableQuantity": max(
                            line.quantity - reserved.get(line.id, 0), 0
                        ),
                    }
                    for line in order.lines
                ],
            }
        raise RuntimeError("Tenant database session was not created.")

    async def list_requests(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
        request_type: str | None,
        shop_id: UUID | None = None,
        reason: str | None = None,
        applied_from: datetime | None = None,
        applied_to: datetime | None = None,
        rma: str | None = None,
    ) -> ReturnRequestPage:
        filters = []
        if status:
            filters.append(ReturnRequest.status == status)
        if request_type:
            filters.append(ReturnRequest.request_type == request_type)
        if shop_id:
            filters.append(ReturnRequest.shop_id == shop_id)
        if reason:
            pattern = f"%{reason}%"
            filters.append(
                or_(
                    ReturnRequest.reason_code.ilike(pattern),
                    ReturnRequest.platform_reason_text.ilike(pattern),
                )
            )
        application_time = func.coalesce(
            ReturnRequest.platform_created_at, ReturnRequest.created_at
        )
        if applied_from:
            filters.append(application_time >= applied_from)
        if applied_to:
            filters.append(application_time <= applied_to)
        if rma:
            filters.append(
                ReturnRequest.rma.has(ReturnRma.rma_number.ilike(f"%{rma}%"))
            )
        async for session in self._database.session(tenant_id):
            requests = await session.scalars(
                request_select()
                .where(*filters)
                .order_by(ReturnRequest.created_at.desc(), ReturnRequest.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            total = await session.scalar(
                select(func.count()).select_from(ReturnRequest).where(*filters)
            )
            return ReturnRequestPage(
                [return_request_record(item) for item in requests.unique().all()],
                total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_request(
        self, tenant_id: UUID, request_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            request = await session.scalar(
                request_select().where(ReturnRequest.id == request_id)
            )
            return return_request_record(request) if request else None
        return None

    async def create_request(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID,
        order_id: UUID,
        request_type: str,
        reason_code: str,
        customer_note: str | None,
        items: list[ReturnItemInput],
    ) -> dict[str, object]:
        validate_return_items(items)
        async for session in self._database.session(tenant_id):
            order = await session.scalar(
                select(Order)
                .options(selectinload(Order.lines))
                .where(Order.id == order_id)
                .with_for_update()
            )
            if order is None:
                raise ReturnNotFoundError("Original sales order was not found.")
            lines = {line.id: line for line in order.lines}
            if {item.order_line_id for item in items} - lines.keys():
                raise ReturnValidationError(
                    "A selected order line does not belong to the original order."
                )
            reserved = await reserved_quantities(
                session, order.id, [item.order_line_id for item in items]
            )
            for item in items:
                available = lines[item.order_line_id].quantity - reserved.get(
                    item.order_line_id, 0
                )
                if item.requested_quantity > available:
                    raise ReturnConflictError(
                        "Requested quantity exceeds the maximum returnable quantity."
                    )
            request = ReturnRequest(
                tenant_id=tenant_id,
                request_number=domain_number("RR"),
                order_id=order.id,
                shop_id=order.shop_id,
                request_type=request_type,
                status="pending_review",
                reason_code=reason_code,
                customer_note=customer_note,
                created_by_user_id=actor_user_id,
                items=[
                    ReturnRequestItem(
                        tenant_id=tenant_id,
                        order_line_id=item.order_line_id,
                        requested_quantity=item.requested_quantity,
                        reason_code=item.reason_code,
                        note=item.note,
                    )
                    for item in items
                ],
            )
            session.add(request)
            await session.commit()
            return return_request_record(await reload_request(session, request.id))
        raise RuntimeError("Tenant database session was not created.")

    async def review_request(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID,
        request_id: UUID,
        decision: str,
        version_id: int,
        note: str | None,
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            request = await session.scalar(
                request_select().where(ReturnRequest.id == request_id).with_for_update()
            )
            if request is None:
                raise ReturnNotFoundError("Return request was not found.")
            if request.status != "pending_review":
                raise ReturnConflictError("Only pending requests can be reviewed.")
            if request.source != "local":
                raise ReturnConflictError(
                    "Platform return requests must be handled on the source platform."
                )
            if request.version_id != version_id:
                raise ReturnConflictError("Return request version is stale.")
            request.reviewed_by_user_id = actor_user_id
            request.reviewed_at = datetime.now(UTC)
            request.review_note = note
            request.status = "approved" if decision == "approve" else "rejected"
            if decision == "approve":
                await create_rma_and_task(session, tenant_id, request, actor_user_id)
            await session.commit()
            return return_request_record(await reload_request(session, request.id))
        raise RuntimeError("Tenant database session was not created.")
