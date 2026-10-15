from erp_api.services.finance_reconciliation import (
    payment_statement_reconciliation,
    statement_identity,
    statement_transaction_reconciliation,
    transaction_identity,
)


def test_transaction_identity_does_not_double_count_refund_breakdown() -> None:
    result = transaction_identity(
        revenue_amount_minor=8_000,
        refund_amount_minor=-2_000,
        shipping_amount_minor=500,
        fee_amount_minor=-900,
        adjustment_amount_minor=100,
        settlement_amount_minor=7_700,
    )

    assert result.expected_amount_minor == 7_700
    assert result.difference_minor == 0
    assert result.status == "matched"


def test_statement_identity_preserves_signed_deductions() -> None:
    result = statement_identity(
        revenue_amount_minor=10_000,
        fee_amount_minor=-1_200,
        adjustment_amount_minor=-300,
        settlement_amount_minor=8_500,
    )

    assert result.expected_amount_minor == 8_500
    assert result.difference_minor == 0


def test_statement_transaction_difference_is_actual_minus_expected() -> None:
    result = statement_transaction_reconciliation(
        statement_amount_minor=9_500,
        transaction_amount_minor=9_400,
    )

    assert result.expected_amount_minor == 9_400
    assert result.actual_amount_minor == 9_500
    assert result.difference_minor == 100
    assert result.status == "mismatched"


def test_payment_statement_difference_is_payment_minus_linked_statements() -> None:
    result = payment_statement_reconciliation(
        payment_amount_minor=12_000,
        linked_statement_amount_minor=11_750,
    )

    assert result.difference_minor == 250
    assert result.status == "mismatched"
