from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from erp_api.services.tiktok_finance_models import (
    FinanceOrderTransaction,
    FinancePaymentPage,
    FinanceStatementPage,
    FinanceStatementTransactionPage,
    FinanceUnsettledTransactionPage,
)
from erp_api.services.tiktok_finance_parsing import validate_resource_id
from erp_api.services.tiktok_finance_schemas import (
    parse_order_transactions_response,
    parse_payments_response,
    parse_statement_transactions_response,
    parse_statements_response,
    parse_unsettled_transactions_response,
)
from erp_api.services.tiktok_transport import TikTokRequest, TikTokTransport

STATEMENTS_PATH = "/finance/202309/statements"
PAYMENTS_PATH = "/finance/202605/payments"
STATEMENT_TRANSACTIONS_PATH = (
    "/finance/202501/statements/{statement_id}/statement_transactions"
)
ORDER_TRANSACTIONS_PATH = "/finance/202501/orders/{order_id}/statement_transactions"
UNSETTLED_TRANSACTIONS_PATH = "/finance/202507/orders/unsettled"
PAYMENT_STATUSES = frozenset({"PAID", "PROCESSING", "FAILED"})
MAX_WINDOW = timedelta(days=30)


class TikTokFinanceClient(Protocol):
    async def list_statements(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
        payment_status: str | None = None,
    ) -> FinanceStatementPage: ...

    async def list_payments(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinancePaymentPage: ...

    async def list_statement_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        statement_id: str,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinanceStatementTransactionPage: ...

    async def get_order_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        order_id: str,
    ) -> FinanceOrderTransaction: ...

    async def list_unsettled_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinanceUnsettledTransactionPage: ...


class HttpTikTokFinanceClient:
    def __init__(
        self,
        transport: TikTokTransport,
        *,
        statements_path: str = STATEMENTS_PATH,
        payments_path: str = PAYMENTS_PATH,
        statement_transactions_path: str = STATEMENT_TRANSACTIONS_PATH,
        order_transactions_path: str = ORDER_TRANSACTIONS_PATH,
        unsettled_transactions_path: str = UNSETTLED_TRANSACTIONS_PATH,
    ) -> None:
        self._transport = transport
        self._statements_path = statements_path
        self._payments_path = payments_path
        self._statement_transactions_path = statement_transactions_path
        self._order_transactions_path = order_transactions_path
        self._unsettled_transactions_path = unsettled_transactions_path

    async def list_statements(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
        payment_status: str | None = None,
    ) -> FinanceStatementPage:
        query = _window_query(
            shop_cipher,
            from_time,
            to_time,
            page_token,
            page_size,
            start_key="statement_time_ge",
            end_key="statement_time_lt",
            sort_field="statement_time",
        )
        if payment_status is not None:
            if payment_status not in PAYMENT_STATUSES:
                raise ValueError("payment_status is not supported.")
            query["payment_status"] = payment_status
        payload = await self._transport.request(
            TikTokRequest("GET", self._statements_path, query=query),
            access_token=access_token,
        )
        return parse_statements_response(payload)

    async def list_payments(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinancePaymentPage:
        query = _window_query(
            shop_cipher,
            from_time,
            to_time,
            page_token,
            page_size,
            start_key="create_time_ge",
            end_key="create_time_lt",
            sort_field="create_time",
        )
        payload = await self._transport.request(
            TikTokRequest("GET", self._payments_path, query=query),
            access_token=access_token,
        )
        return parse_payments_response(payload)

    async def list_statement_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        statement_id: str,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinanceStatementTransactionPage:
        _validate_scope(shop_cipher, page_size)
        validate_resource_id(statement_id, "statement_id")
        query = _page_query(shop_cipher, page_token, page_size)
        query.update({"sort_field": "order_create_time", "sort_order": "ASC"})
        payload = await self._transport.request(
            TikTokRequest(
                "GET",
                self._statement_transactions_path.format(statement_id=statement_id),
                query=query,
            ),
            access_token=access_token,
        )
        return parse_statement_transactions_response(payload)

    async def get_order_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        order_id: str,
    ) -> FinanceOrderTransaction:
        _validate_scope(shop_cipher, 20)
        validate_resource_id(order_id, "order_id")
        payload = await self._transport.request(
            TikTokRequest(
                "GET",
                self._order_transactions_path.format(order_id=order_id),
                query={"shop_cipher": shop_cipher},
            ),
            access_token=access_token,
        )
        return parse_order_transactions_response(payload)

    async def list_unsettled_transactions(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        from_time: datetime,
        to_time: datetime,
        page_token: str | None = None,
        page_size: int = 20,
    ) -> FinanceUnsettledTransactionPage:
        query = _window_query(
            shop_cipher,
            from_time,
            to_time,
            page_token,
            page_size,
            start_key="search_time_ge",
            end_key="search_time_lt",
            sort_field="order_create_time",
        )
        payload = await self._transport.request(
            TikTokRequest("GET", self._unsettled_transactions_path, query=query),
            access_token=access_token,
        )
        return parse_unsettled_transactions_response(payload)


def _window_query(
    shop_cipher: str,
    from_time: datetime,
    to_time: datetime,
    page_token: str | None,
    page_size: int,
    *,
    start_key: str,
    end_key: str,
    sort_field: str,
) -> dict[str, str]:
    _validate_scope(shop_cipher, page_size)
    if from_time.tzinfo is None or to_time.tzinfo is None:
        raise ValueError("Finance windows must be timezone-aware.")
    if from_time >= to_time:
        raise ValueError("Finance window must satisfy from_time < to_time.")
    if to_time - from_time > MAX_WINDOW:
        raise ValueError("Finance window must not exceed 30 days.")
    return {
        **_page_query(shop_cipher, page_token, page_size),
        start_key: str(int(from_time.timestamp())),
        end_key: str(int(to_time.timestamp())),
        "sort_field": sort_field,
        "sort_order": "ASC",
    }


def _page_query(
    shop_cipher: str, page_token: str | None, page_size: int
) -> dict[str, str]:
    return {
        "shop_cipher": shop_cipher,
        "page_size": str(page_size),
        **({"page_token": page_token} if page_token else {}),
    }


def _validate_scope(shop_cipher: str, page_size: int) -> None:
    if not shop_cipher:
        raise ValueError("shop_cipher is required.")
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100.")
