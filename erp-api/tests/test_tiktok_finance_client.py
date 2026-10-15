from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from erp_api.services.tiktok_finance_client import HttpTikTokFinanceClient
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


class RecordingTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[tuple[TikTokRequest, str | None]] = []

    async def request(
        self, request: TikTokRequest, *, access_token: str | None = None, **kwargs
    ) -> dict[str, Any]:
        self.requests.append((request, access_token))
        return self.responses.pop(0)


def test_finance_client_uses_verified_versions_and_delegates_to_transport() -> None:
    transport = RecordingTransport(
        [
            {"data": {"statements": [], "next_page_token": ""}},
            {"data": {"payments": [], "next_page_token": ""}},
        ]
    )
    client = HttpTikTokFinanceClient(transport)  # type: ignore[arg-type]
    start = datetime(2026, 7, 22, tzinfo=UTC)
    end = datetime(2026, 8, 21, tzinfo=UTC)

    asyncio.run(
        client.list_statements(
            "token",
            shop_cipher="cipher",
            from_time=start,
            to_time=end,
            page_size=20,
            payment_status="PAID",
        )
    )
    asyncio.run(
        client.list_payments(
            "token",
            shop_cipher="cipher",
            from_time=start,
            to_time=end,
            page_token="next",
        )
    )

    statement_request, token = transport.requests[0]
    assert statement_request.path == "/finance/202309/statements"
    assert statement_request.method == "GET"
    assert statement_request.query == {
        "shop_cipher": "cipher",
        "statement_time_ge": "1784678400",
        "statement_time_lt": "1787270400",
        "page_size": "20",
        "payment_status": "PAID",
        "sort_field": "statement_time",
        "sort_order": "ASC",
    }
    assert token == "token"
    payment_request = transport.requests[1][0]
    assert payment_request.path == "/finance/202605/payments"
    assert payment_request.query["create_time_ge"] == "1784678400"
    assert payment_request.query["create_time_lt"] == "1787270400"
    assert payment_request.query["page_token"] == "next"
    assert payment_request.query["sort_field"] == "create_time"
    assert payment_request.query["sort_order"] == "ASC"


def test_finance_client_builds_safe_resource_paths_and_unsettled_window() -> None:
    transport = RecordingTransport(
        [
            {
                "data": {
                    "id": "s-1",
                    "currency": "USD",
                    "status": "PAID",
                    "create_time": 1,
                    "payable_amount": "0",
                    "total_reserve_amount": "0",
                    "total_settlement_amount": "0",
                    "total_count": 0,
                    "next_page_token": "",
                    "total_settlement_breakdown": {
                        "total_adjustment_amount": "0",
                        "total_fee_tax_amount": "0",
                        "total_revenue_amount": "0",
                        "total_shipping_cost_amount": "0",
                    },
                    "transactions": [],
                }
            },
            {
                "data": {
                    "order_id": "o-1",
                    "currency": "USD",
                    "order_create_time": 1,
                    "revenue_amount": "0",
                    "fee_and_tax_amount": "0",
                    "shipping_cost_amount": "0",
                    "settlement_amount": "0",
                    "total_count": 0,
                    "sku_transactions": [],
                }
            },
            {
                "data": {
                    "next_page_token": "",
                    "total_count": 0,
                    "sum_est_revenue_amount": "0",
                    "sum_est_fee_amount": "0",
                    "sum_est_adjustment_amount": "0",
                    "sum_est_settlement_amount": "0",
                    "transactions": [],
                }
            },
        ]
    )
    client = HttpTikTokFinanceClient(transport)  # type: ignore[arg-type]
    start = datetime(2026, 7, 22, tzinfo=UTC)
    end = datetime(2026, 8, 21, tzinfo=UTC)

    asyncio.run(
        client.list_statement_transactions(
            "token", shop_cipher="cipher", statement_id="s-1"
        )
    )
    asyncio.run(
        client.get_order_transactions("token", shop_cipher="cipher", order_id="o-1")
    )
    asyncio.run(
        client.list_unsettled_transactions(
            "token",
            shop_cipher="cipher",
            from_time=start,
            to_time=end,
        )
    )

    assert transport.requests[0][0].path == (
        "/finance/202501/statements/s-1/statement_transactions"
    )
    assert transport.requests[1][0].path == (
        "/finance/202501/orders/o-1/statement_transactions"
    )
    unsettled = transport.requests[2][0]
    assert unsettled.path == "/finance/202507/orders/unsettled"
    assert unsettled.query["search_time_ge"] == "1784678400"
    assert unsettled.query["search_time_lt"] == "1787270400"
    assert unsettled.query["sort_field"] == "order_create_time"
    assert unsettled.query["sort_order"] == "ASC"
    assert transport.requests[0][0].query["sort_field"] == "order_create_time"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shop_cipher": "", "page_size": 20},
        {"shop_cipher": "cipher", "page_size": 0},
        {"shop_cipher": "cipher", "page_size": 101},
    ],
)
def test_finance_client_rejects_invalid_scope_and_pagination(kwargs) -> None:
    client = HttpTikTokFinanceClient(RecordingTransport([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        asyncio.run(
            client.list_statements(
                "token",
                from_time=datetime(2026, 7, 22, tzinfo=UTC),
                to_time=datetime(2026, 8, 21, tzinfo=UTC),
                **kwargs,
            )
        )


def test_finance_client_rejects_naive_or_reversed_windows_and_unsafe_ids() -> None:
    client = HttpTikTokFinanceClient(RecordingTransport([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        asyncio.run(
            client.list_payments(
                "token",
                shop_cipher="cipher",
                from_time=datetime(2026, 7, 22),  # noqa: DTZ001 - invalid input
                to_time=datetime(2026, 8, 21, tzinfo=UTC),
            )
        )
    with pytest.raises(ValueError):
        asyncio.run(
            client.list_unsettled_transactions(
                "token",
                shop_cipher="cipher",
                from_time=datetime(2026, 8, 21, tzinfo=UTC),
                to_time=datetime(2026, 7, 22, tzinfo=UTC),
            )
        )
    with pytest.raises(ValueError):
        asyncio.run(
            client.get_order_transactions(
                "token", shop_cipher="cipher", order_id="../unsafe"
            )
        )


def test_finance_client_reuses_transport_signing_retry_after_and_headers() -> None:
    attempts = 0
    delays: list[float] = []
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        captured.append(request)
        if attempts == 1:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"code": "limited"}
            )
        return httpx.Response(
            200, json={"code": 0, "data": {"statements": [], "next_page_token": ""}}
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=1,
        http_transport=httpx.MockTransport(handler),
        sleep=record_sleep,
        clock=lambda: 1_700_000_000,
    )
    client = HttpTikTokFinanceClient(transport)

    asyncio.run(
        client.list_statements(
            "access-token",
            shop_cipher="cipher",
            from_time=datetime(2026, 7, 22, tzinfo=UTC),
            to_time=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert attempts == 2
    assert delays == [2.0]
    assert captured[-1].url.params["sign"]
    assert captured[-1].headers["x-tts-access-token"] == "access-token"


def test_finance_client_keeps_transport_platform_errors_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": "secret-code", "message": "secret-message"}
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )
    client = HttpTikTokFinanceClient(transport)

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            client.list_statements(
                "token",
                shop_cipher="cipher",
                from_time=datetime(2026, 7, 22, tzinfo=UTC),
                to_time=datetime(2026, 8, 21, tzinfo=UTC),
            )
        )

    assert str(error.value) == "TikTok API rejected the request."
    assert "secret-message" not in str(error.value)
