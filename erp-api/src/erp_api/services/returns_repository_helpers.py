from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.order import Order
from erp_api.models.return_request import ReturnRequest, ReturnRequestItem
from erp_api.models.return_rma import ReturnRma


async def reserved_quantities(session, order_id: UUID, line_ids: list[UUID]):
    if not line_ids:
        return {}
    rows = await session.execute(
        select(
            ReturnRequestItem.order_line_id,
            func.sum(ReturnRequestItem.requested_quantity),
        )
        .join(ReturnRequest)
        .where(
            ReturnRequest.order_id == order_id,
            ReturnRequest.status.in_(("pending_review", "approved")),
            ReturnRequestItem.order_line_id.in_(line_ids),
        )
        .group_by(ReturnRequestItem.order_line_id)
    )
    return {line_id: int(quantity) for line_id, quantity in rows}


async def find_order(session, reference: str) -> Order | None:
    try:
        order_id = UUID(reference)
    except ValueError:
        order_id = None
    return await session.scalar(
        select(Order)
        .options(selectinload(Order.lines))
        .where(
            or_(
                Order.id == order_id if order_id else False,
                Order.order_number == reference,
            )
        )
        .order_by(Order.placed_at.desc(), Order.id)
    )


async def create_rma_and_task(session, tenant_id, request, actor_user_id) -> None:
    rma = ReturnRma(
        tenant_id=tenant_id,
        return_request_id=request.id,
        rma_number=domain_number("RMA"),
        status="open",
        generated_by_user_id=actor_user_id,
    )
    session.add(rma)
    await session.flush()
    task = LogisticsTask(
        tenant_id=tenant_id,
        task_number=domain_number("RT"),
        source_type=request.request_type,
        direction="reverse",
        source_reference_id=rma.id,
        source_number=rma.rma_number,
        order_id=request.order_id,
        return_rma_id=rma.id,
        shop_id=request.shop_id,
        priority="normal",
        status="pending_pack",
        note=request.review_note,
        created_by_user_id=actor_user_id,
    )
    for request_item in request.items:
        line = request_item.order_line
        task.items.append(
            LogisticsTaskItem(
                tenant_id=tenant_id,
                source_line_id=request_item.id,
                order_line_id=line.id,
                platform_product_id=line.platform_product_id,
                platform_sku_id=line.platform_sku_id,
                seller_sku=line.seller_sku,
                product_name=line.product_name,
                sku_name=line.sku_name,
                planned_quantity=request_item.requested_quantity,
                packed_quantity=0,
                shipped_quantity=0,
            )
        )
    task.operations.append(
        LogisticsTaskOperation(
            tenant_id=tenant_id,
            operation_type="reverse_created",
            to_status="pending_pack",
            actor_user_id=actor_user_id,
            note=request.review_note,
            details={
                "direction": "reverse",
                "returnRequestId": str(request.id),
                "rmaId": str(rma.id),
            },
        )
    )
    session.add(task)


def request_select():
    return select(ReturnRequest).options(
        selectinload(ReturnRequest.order),
        selectinload(ReturnRequest.items).selectinload(ReturnRequestItem.order_line),
        selectinload(ReturnRequest.rma).selectinload(ReturnRma.reverse_task),
    )


async def reload_request(session, request_id: UUID) -> ReturnRequest:
    stored = await session.scalar(
        request_select()
        .where(ReturnRequest.id == request_id)
        .execution_options(populate_existing=True)
    )
    if stored is None:
        raise RuntimeError("Return request could not be reloaded.")
    return stored


def domain_number(prefix: str) -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"
