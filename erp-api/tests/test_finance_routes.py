from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import FINANCE_VIEW
from erp_api.routers import finance
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.finance_repository import FinancePage


class FakeFinanceRepository:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.shop_id = uuid4()
        self.statement_id = uuid4()
        self.transaction_id = uuid4()
        self.order_id = uuid4()
        self.last_kwargs: dict[str, object] = {}

    async def overview(self, tenant_id: UUID, **kwargs):
        self.last_kwargs = kwargs
        return [
            {
                "currency": "USD",
                "gross_revenue_minor": 10_000,
                "refund_amount_minor": -500,
                "platform_fee_minor": -1_000,
                "affiliate_commission_minor": -200,
                "shipping_amount_minor": 300,
                "tax_amount_minor": 0,
                "adjustment_amount_minor": 0,
                "settlement_amount_minor": 9_300,
                "paid_amount_minor": 9_000,
                "statement_transaction_difference_minor": 0,
                "payment_statement_difference_minor": -300,
                "final_count": 2,
                "estimated_count": 1,
                "trend": [
                    {
                        "date": datetime(2026, 8, 20, tzinfo=UTC),
                        "revenue_amount_minor": 10_000,
                        "refund_amount_minor": -500,
                        "fee_amount_minor": -1_000,
                        "settlement_amount_minor": 9_300,
                    }
                ],
            }
        ]

    async def list_statements(self, tenant_id: UUID, **kwargs):
        self.last_kwargs = kwargs
        return FinancePage([self._statement()], 1)

    async def get_statement(self, tenant_id: UUID, statement_id: UUID):
        return self._statement() if statement_id == self.statement_id else None

    async def list_transactions(self, tenant_id: UUID, **kwargs):
        self.last_kwargs = kwargs
        return FinancePage([self._transaction()], 1)

    async def get_transaction(self, tenant_id: UUID, transaction_id: UUID):
        return self._transaction() if transaction_id == self.transaction_id else None

    async def list_payments(self, tenant_id: UUID, **kwargs):
        self.last_kwargs = kwargs
        return FinancePage([self._payment()], 1)

    async def reconciliation(self, tenant_id: UUID, **kwargs):
        stamp = datetime(2026, 8, 20, tzinfo=UTC)
        return {
            "items": [
                {
                    "kind": "missing_order",
                    "entity_type": "transaction",
                    "entity_id": self.transaction_id,
                    "reference": "order-1",
                    "currency": "USD",
                    "expected_amount_minor": 9000,
                    "actual_amount_minor": 9000,
                    "difference_minor": 0,
                    "severity": "medium",
                    "occurred_at": stamp,
                }
            ],
            "total": 1,
        }

    async def order_summary(self, tenant_id: UUID, order_id: UUID):
        if order_id != self.order_id:
            return None
        return {
            "order": SimpleNamespace(
                id=self.order_id,
                order_number="erp-order-1",
                platform_order_id="platform-order-1",
            ),
            "totals": {
                "USD": {
                    "transaction_count": 1,
                    "revenue_amount_minor": 10_000,
                    "fee_amount_minor": -1_000,
                    "settlement_amount_minor": 9_000,
                }
            },
            "transactions": [self._transaction()],
        }

    async def _export_rows(self):
        yield "\ufeffid\r\n"
        yield "transaction-1\r\n"

    def stream_export(self, tenant_id: UUID, **kwargs):
        self.last_kwargs = kwargs
        return self._export_rows()

    def _statement(self):
        stamp = datetime(2026, 8, 20, tzinfo=UTC)
        statement = SimpleNamespace(
            id=self.statement_id,
            shop_id=self.shop_id,
            platform_statement_id="statement-1",
            status="available",
            payment_status="paid",
            currency="USD",
            revenue_amount_minor=10_000,
            fee_amount_minor=-1_000,
            adjustment_amount_minor=0,
            settlement_amount_minor=9_000,
            statement_start_at=stamp,
            statement_end_at=stamp,
            platform_created_at=stamp,
            platform_updated_at=stamp,
            synced_at=stamp,
        )
        return {
            "statement": statement,
            "transaction_count": 1,
            "transaction_amount_minor": 9_000,
            "payment_count": 1,
            "payment_amount_minor": 9_000,
            "transactions": [],
            "payments": [],
        }

    def _transaction(self):
        stamp = datetime(2026, 8, 20, tzinfo=UTC)
        return {
            "transaction": SimpleNamespace(
                id=self.transaction_id,
                shop_id=self.shop_id,
                platform_transaction_id="transaction-1",
                statement_id=self.statement_id,
                order_id=self.order_id,
                platform_order_id="platform-order-1",
                transaction_type="order",
                status="settled",
                is_estimated=False,
                currency="USD",
                revenue_amount_minor=10_000,
                refund_amount_minor=-500,
                shipping_amount_minor=0,
                fee_amount_minor=-1_000,
                adjustment_amount_minor=0,
                settlement_amount_minor=9_000,
                occurred_at=stamp,
                platform_updated_at=stamp,
                synced_at=stamp,
                data_completeness="final",
            ),
            "order_number": "erp-order-1",
            "platform_statement_id": "statement-1",
            "components": [],
        }

    def _payment(self):
        stamp = datetime(2026, 8, 20, tzinfo=UTC)
        return {
            "payment": SimpleNamespace(
                id=uuid4(),
                shop_id=self.shop_id,
                platform_payment_id="payment-1",
                status="paid",
                currency="USD",
                payment_amount_minor=9_100,
                initiated_at=stamp,
                paid_at=stamp,
                bank_reference_masked="****1234",
                platform_updated_at=stamp,
                synced_at=stamp,
            ),
            "statement_count": 1,
            "statement_amount_minor": 9_000,
        }


def _client(repository: FakeFinanceRepository, permissions: list[str]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(finance.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=repository.tenant_id
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(), name="Admin", username="admin", roles=[], permissions=permissions
    )
    app.dependency_overrides[finance._repository] = lambda: repository
    return TestClient(app)


def test_finance_overview_is_currency_isolated_and_camel_case() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get("/api/finance/overview?currency=usd")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["currency"] == "USD"
    assert item["grossRevenueMinor"] == 10_000
    assert item["basis"] == "mixed"
    assert item["contributionProfitMinor"] is None
    assert item["trend"][0] == {
        "date": "2026-08-20T00:00:00Z",
        "revenueAmountMinor": 10_000,
        "refundAmountMinor": -500,
        "feeAmountMinor": -1_000,
        "settlementAmountMinor": 9_300,
    }


def test_finance_overview_forwards_the_requested_settlement_basis() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get("/api/finance/overview?isEstimated=false")

    assert response.status_code == 200
    assert repository.last_kwargs["query"].is_estimated is False


def test_finance_statement_list_forwards_server_pagination_and_filters() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get(
            f"/api/finance/statements?page=2&pageSize=25&shopId={repository.shop_id}"
        )

    assert response.status_code == 200
    assert response.json()["page"] == 2
    assert response.json()["pageSize"] == 25
    assert repository.last_kwargs["page"] == 2
    assert repository.last_kwargs["page_size"] == 25


def test_finance_statement_detail_returns_404_inside_tenant_scope() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get(f"/api/finance/statements/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_finance_read_endpoints_require_finance_view() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, []) as client:
        response = client.get("/api/finance/overview")

    assert response.status_code == 403


def test_finance_transaction_list_includes_order_link_and_identity() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get(
            "/api/finance/transactions?keyword=erp-order-1&paymentState=refunded"
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["orderPath"] == f"/orders/{repository.order_id}"
    assert item["identityStatus"] == "matched"
    assert repository.last_kwargs["query"].keyword == "erp-order-1"
    assert repository.last_kwargs["query"].payment_state == "refunded"


def test_finance_transaction_list_rejects_unknown_payment_state() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get("/api/finance/transactions?paymentState=unknown")

    assert response.status_code == 422


def test_finance_payment_list_exposes_payment_statement_difference() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get("/api/finance/payments")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["differenceMinor"] == 100
    assert item["recexample81340158"] == "mismatched"


def test_finance_reconciliation_and_order_summary_are_read_only_views() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        issues = client.get("/api/finance/reconciliation")
        order = client.get(f"/api/finance/orders/{repository.order_id}/summary")

    assert issues.status_code == 200
    assert issues.json()["items"][0]["kind"] == "missing_order"
    assert order.status_code == 200
    assert order.json()["totals"][0]["settlementAmountMinor"] == 9_000


def test_finance_export_streams_with_the_same_query_filters() -> None:
    repository = FakeFinanceRepository()
    with _client(repository, [FINANCE_VIEW]) as client:
        response = client.get(
            f"/api/finance/export?resource=transactions&shopId={repository.shop_id}"
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbfid")
    assert repository.last_kwargs["query"].shop_id == repository.shop_id
