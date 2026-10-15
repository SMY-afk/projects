from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from uuid import UUID, uuid4

from erp_api.models.finance_payment import FinancePayment, FinancePaymentStatement
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction

STATEMENT_NUMBER = "E2E-STATEMENT-0001"
PAYMENT_NUMBER = "E2E-PAYMENT-0001"


def finance_parent_rows(
    *,
    scenario_id: UUID,
    tenant_id: UUID,
    shop_id: UUID,
    statement_id: UUID,
    payment_id: UUID,
    occurred_at: datetime,
) -> list[object]:
    return [
        FinanceStatement(
            id=statement_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            platform_statement_id=STATEMENT_NUMBER,
            status="available",
            payment_status="PAID",
            currency="USD",
            revenue_amount_minor=10_000,
            fee_amount_minor=-1_000,
            adjustment_amount_minor=0,
            settlement_amount_minor=9_000,
            statement_start_at=occurred_at,
            statement_end_at=occurred_at,
            platform_created_at=occurred_at,
            platform_updated_at=occurred_at,
            synced_at=occurred_at,
            source_hash=sha256(f"{scenario_id}:statement".encode()).hexdigest(),
        ),
        FinancePayment(
            id=payment_id,
            tenant_id=tenant_id,
            shop_id=shop_id,
            platform_payment_id=PAYMENT_NUMBER,
            status="PAID",
            currency="USD",
            payment_amount_minor=9_000,
            initiated_at=occurred_at,
            paid_at=occurred_at,
            bank_reference_masked="****4321",
            platform_updated_at=occurred_at,
            synced_at=occurred_at,
            source_hash=sha256(f"{scenario_id}:payment".encode()).hexdigest(),
        ),
    ]


def finance_transaction_rows(
    *,
    scenario_id: UUID,
    tenant_id: UUID,
    shop_id: UUID,
    statement_id: UUID,
    order_id: UUID,
    platform_order_id: str,
    occurred_at: datetime,
) -> list[FinanceTransaction]:
    return [
        FinanceTransaction(
            id=uuid4(),
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_record_key=f"e2e-transaction-{scenario_id.hex}",
            platform_transaction_id=f"e2e-transaction-{scenario_id.hex}",
            statement_id=statement_id,
            order_id=order_id,
            platform_order_id=platform_order_id,
            transaction_type="ORDER",
            status="settled",
            is_estimated=False,
            currency="USD",
            revenue_amount_minor=10_000,
            refund_amount_minor=0,
            shipping_amount_minor=0,
            fee_amount_minor=-1_000,
            adjustment_amount_minor=0,
            settlement_amount_minor=9_000,
            occurred_at=occurred_at,
            platform_updated_at=occurred_at,
            synced_at=occurred_at,
            source_hash=sha256(f"{scenario_id}:transaction".encode()).hexdigest(),
            data_completeness="final",
        ),
        FinanceTransaction(
            id=uuid4(),
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_record_key=f"e2e-unsettled-{scenario_id.hex}",
            platform_transaction_id=f"e2e-unsettled-{scenario_id.hex}",
            statement_id=None,
            order_id=None,
            platform_order_id=f"e2e-missing-order-{scenario_id.hex}",
            transaction_type="ORDER",
            status="PROCESSING",
            is_estimated=True,
            currency="USD",
            revenue_amount_minor=5_000,
            refund_amount_minor=0,
            shipping_amount_minor=0,
            fee_amount_minor=-500,
            adjustment_amount_minor=0,
            settlement_amount_minor=4_500,
            occurred_at=occurred_at,
            platform_updated_at=None,
            synced_at=occurred_at,
            source_hash=sha256(f"{scenario_id}:unsettled".encode()).hexdigest(),
            data_completeness="estimated",
        ),
        FinanceTransaction(
            id=uuid4(),
            tenant_id=tenant_id,
            shop_id=shop_id,
            source_record_key=f"e2e-refunded-{scenario_id.hex}",
            platform_transaction_id=f"e2e-refunded-{scenario_id.hex}",
            statement_id=statement_id,
            order_id=None,
            platform_order_id=f"e2e-refunded-order-{scenario_id.hex}",
            transaction_type="ORDER",
            status="settled",
            is_estimated=False,
            currency="USD",
            revenue_amount_minor=5_000,
            refund_amount_minor=-5_000,
            shipping_amount_minor=0,
            fee_amount_minor=0,
            adjustment_amount_minor=0,
            settlement_amount_minor=0,
            occurred_at=occurred_at,
            platform_updated_at=occurred_at,
            synced_at=occurred_at,
            source_hash=sha256(f"{scenario_id}:refunded".encode()).hexdigest(),
            data_completeness="final",
        ),
    ]


def finance_payment_link(
    *, tenant_id: UUID, payment_id: UUID, statement_id: UUID
) -> FinancePaymentStatement:
    return FinancePaymentStatement(
        tenant_id=tenant_id,
        payment_id=payment_id,
        statement_id=statement_id,
    )
