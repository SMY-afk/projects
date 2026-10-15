from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationResult:
    expected_amount_minor: int
    actual_amount_minor: int
    difference_minor: int
    status: str


def _result(*, expected: int, actual: int) -> ReconciliationResult:
    difference = actual - expected
    return ReconciliationResult(
        expected_amount_minor=expected,
        actual_amount_minor=actual,
        difference_minor=difference,
        status="matched" if difference == 0 else "mismatched",
    )


def transaction_identity(
    *,
    revenue_amount_minor: int,
    refund_amount_minor: int,
    shipping_amount_minor: int,
    fee_amount_minor: int,
    adjustment_amount_minor: int,
    settlement_amount_minor: int,
) -> ReconciliationResult:
    # Refund is an audited revenue breakdown, not an additional term.
    del refund_amount_minor
    expected = (
        revenue_amount_minor
        + shipping_amount_minor
        + fee_amount_minor
        + adjustment_amount_minor
    )
    return _result(expected=expected, actual=settlement_amount_minor)


def statement_identity(
    *,
    revenue_amount_minor: int,
    fee_amount_minor: int,
    adjustment_amount_minor: int,
    settlement_amount_minor: int,
) -> ReconciliationResult:
    expected = revenue_amount_minor + fee_amount_minor + adjustment_amount_minor
    return _result(expected=expected, actual=settlement_amount_minor)


def statement_transaction_reconciliation(
    *, statement_amount_minor: int, transaction_amount_minor: int
) -> ReconciliationResult:
    return _result(
        expected=transaction_amount_minor,
        actual=statement_amount_minor,
    )


def payment_statement_reconciliation(
    *, payment_amount_minor: int, linked_statement_amount_minor: int
) -> ReconciliationResult:
    return _result(
        expected=linked_statement_amount_minor,
        actual=payment_amount_minor,
    )
