from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from erp_api.core.permissions import FINANCE_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.finance_response import (
    order_summary_response,
    overview_response,
    payment_response,
    reconciliation_item_response,
    statement_detail_response,
    statement_response,
    transaction_response,
)
from erp_api.routers.finance_schemas import (
    FinanceOrderSummaryResponse,
    FinanceOverviewResponse,
    FinancePaymentListResponse,
    FinanceReconciliationResponse,
    FinanceStatementDetailResponse,
    FinanceStatementListResponse,
    FinanceSyncRequest,
    FinanceSyncResponse,
    FinanceTransactionListResponse,
    FinanceTransactionResponse,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.finance_repository import FinanceQuery, FinanceRepository
from erp_api.services.finance_sync_service import (
    FinanceSyncService,
    FinanceSyncWindowError,
)

router = APIRouter(prefix="/finance", tags=["finance"])


def _repository(request: Request) -> FinanceRepository:
    repository = getattr(request.app.state, "finance_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _sync_service(request: Request) -> FinanceSyncService:
    service = getattr(request.app.state, "finance_sync_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def _query(
    shop_id: UUID | None = Query(None, alias="shopId"),
    currency: str | None = Query(None, min_length=3, max_length=3),
    item_status: str | None = Query(None, alias="status"),
    window_from: datetime | None = Query(None, alias="from"),
    window_to: datetime | None = Query(None, alias="to"),
) -> FinanceQuery:
    if window_from and window_from.utcoffset() is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if window_to and window_to.utcoffset() is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if window_from and window_to and window_from >= window_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    return FinanceQuery(
        shop_id=shop_id,
        currency=currency.upper() if currency else None,
        status=item_status,
        window_from=window_from,
        window_to=window_to,
    )


@router.get("/overview", response_model=FinanceOverviewResponse)
async def get_overview(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
    is_estimated: bool | None = Query(None, alias="isEstimated"),
) -> FinanceOverviewResponse:
    query = replace(query, is_estimated=is_estimated)
    rows = await repository.overview(session.tenant_id, query=query)
    return FinanceOverviewResponse(
        items=[overview_response(item, query) for item in rows]
    )


@router.get("/statements", response_model=FinanceStatementListResponse)
async def list_statements(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    payment_status: str | None = Query(None, alias="paymentStatus"),
) -> FinanceStatementListResponse:
    query = replace(query, payment_status=payment_status)
    result = await repository.list_statements(
        session.tenant_id, page=page, page_size=page_size, query=query
    )
    return FinanceStatementListResponse(
        items=[statement_response(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.get("/statements/{statement_id}", response_model=FinanceStatementDetailResponse)
async def get_statement(
    statement_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
) -> FinanceStatementDetailResponse:
    result = await repository.get_statement(session.tenant_id, statement_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return statement_detail_response(result)


@router.get("/transactions", response_model=FinanceTransactionListResponse)
async def list_transactions(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    statement_id: UUID | None = Query(None, alias="statementId"),
    order_id: UUID | None = Query(None, alias="orderId"),
    transaction_type: str | None = Query(None, alias="type"),
    is_estimated: bool | None = Query(None, alias="isEstimated"),
    payment_state: Literal["completed", "refunded", "pending"] | None = Query(
        None, alias="paymentState"
    ),
    keyword: str | None = Query(None, max_length=128),
) -> FinanceTransactionListResponse:
    query = replace(
        query,
        statement_id=statement_id,
        order_id=order_id,
        transaction_type=transaction_type,
        is_estimated=is_estimated,
        payment_state=payment_state,
        keyword=keyword,
    )
    result = await repository.list_transactions(
        session.tenant_id, page=page, page_size=page_size, query=query
    )
    return FinanceTransactionListResponse(
        items=[transaction_response(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.get("/transactions/{transaction_id}", response_model=FinanceTransactionResponse)
async def get_transaction(
    transaction_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
) -> FinanceTransactionResponse:
    result = await repository.get_transaction(session.tenant_id, transaction_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return transaction_response(result)


@router.get("/payments", response_model=FinancePaymentListResponse)
async def list_payments(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
) -> FinancePaymentListResponse:
    result = await repository.list_payments(
        session.tenant_id, page=page, page_size=page_size, query=query
    )
    return FinancePaymentListResponse(
        items=[payment_response(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.get("/reconciliation", response_model=FinanceReconciliationResponse)
async def get_reconciliation(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
) -> FinanceReconciliationResponse:
    result = await repository.reconciliation(session.tenant_id, query=query)
    return FinanceReconciliationResponse(
        items=[reconciliation_item_response(item) for item in result["items"]],
        total=result["total"],
        limit=100,
    )


@router.get("/orders/{order_id}/summary", response_model=FinanceOrderSummaryResponse)
async def get_order_summary(
    order_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
) -> FinanceOrderSummaryResponse:
    result = await repository.order_summary(session.tenant_id, order_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return order_summary_response(result)


@router.get("/export")
async def export_finance(
    resource: Literal["statements", "transactions", "payments"],
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW)),
    repository: FinanceRepository = Depends(_repository),
    query: FinanceQuery = Depends(_query),
) -> StreamingResponse:
    filename = f"finance-{resource}.csv"
    return StreamingResponse(
        repository.stream_export(session.tenant_id, resource=resource, query=query),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/sync", response_model=FinanceSyncResponse)
async def sync_finance(
    payload: FinanceSyncRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(FINANCE_VIEW, SYNC_TRIGGER)),
    service: FinanceSyncService = Depends(_sync_service),
) -> FinanceSyncResponse:
    try:
        result = await service.sync(
            session.tenant_id,
            shop_id=payload.shopId,
            mode=payload.mode,
            window_from=payload.from_,
            window_to=payload.to,
            trigger="manual",
        )
    except FinanceSyncWindowError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from error
    return FinanceSyncResponse(
        runId=result.run_id,
        shopId=result.shop_id,
        status=result.status,
        fetchedCount=result.fetched_count,
        writtenCount=result.written_count,
        recoveryCursor=result.recovery_cursor,
        error=result.error,
    )
