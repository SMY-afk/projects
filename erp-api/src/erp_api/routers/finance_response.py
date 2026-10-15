from __future__ import annotations

from erp_api.routers.finance_schemas import (
    FinanceComponentResponse,
    FinanceOrderCurrencySummaryResponse,
    FinanceOrderSummaryResponse,
    FinanceOverviewItemResponse,
    FinancePaymentResponse,
    FinancePeriodResponse,
    FinanceReconciliationItemResponse,
    FinanceStatementDetailResponse,
    FinanceStatementResponse,
    FinanceTransactionResponse,
    FinanceTrendPointResponse,
    LinkedFinancePaymentResponse,
)
from erp_api.services.finance_reconciliation import (
    payment_statement_reconciliation,
    statement_identity,
    statement_transaction_reconciliation,
    transaction_identity,
)


def overview_response(item, query):
    final_count = int(item["final_count"])
    estimated_count = int(item["estimated_count"])
    if final_count and estimated_count:
        basis = "mixed"
    elif estimated_count:
        basis = "estimated"
    elif final_count:
        basis = "settled"
    else:
        basis = "unavailable"
    reasons = ["product_cost_unavailable"]
    if estimated_count:
        reasons.append("estimated_transactions_present")
    if not final_count and not estimated_count:
        reasons.append("finance_transactions_unavailable")
    completeness = (
        "unavailable"
        if not final_count and not estimated_count
        else "partial"
        if estimated_count
        else "complete"
    )
    settlement = int(item["settlement_amount_minor"])
    paid = int(item["paid_amount_minor"])
    return FinanceOverviewItemResponse(
        period=FinancePeriodResponse(
            **{"from": query.window_from, "to": query.window_to}
        ),
        currency=item["currency"],
        basis=basis,
        grossRevenueMinor=item["gross_revenue_minor"],
        refundAmountMinor=item["refund_amount_minor"],
        platformFeeMinor=item["platform_fee_minor"],
        affiliateCommissionMinor=item["affiliate_commission_minor"],
        shippingAmountMinor=item["shipping_amount_minor"],
        taxAmountMinor=item["tax_amount_minor"],
        adjustmentAmountMinor=item["adjustment_amount_minor"],
        settlementAmountMinor=settlement,
        paidAmountMinor=paid,
        outstandingAmountMinor=settlement - paid,
        statementTransactionDifferenceMinor=item[
            "statement_transaction_difference_minor"
        ],
        paymentStatementDifferenceMinor=item["payment_statement_difference_minor"],
        completeness=completeness,
        missingReasons=reasons,
        trend=[
            FinanceTrendPointResponse(
                date=point["date"],
                revenueAmountMinor=point["revenue_amount_minor"],
                refundAmountMinor=point["refund_amount_minor"],
                feeAmountMinor=point["fee_amount_minor"],
                settlementAmountMinor=point["settlement_amount_minor"],
            )
            for point in item["trend"]
        ],
    )


def transaction_response(row):
    item = row["transaction"]
    identity = transaction_identity(
        revenue_amount_minor=item.revenue_amount_minor,
        refund_amount_minor=item.refund_amount_minor,
        shipping_amount_minor=item.shipping_amount_minor,
        fee_amount_minor=item.fee_amount_minor,
        adjustment_amount_minor=item.adjustment_amount_minor,
        settlement_amount_minor=item.settlement_amount_minor,
    )
    return FinanceTransactionResponse(
        id=item.id,
        shopId=item.shop_id,
        platformTransactionId=item.platform_transaction_id,
        statementId=item.statement_id,
        platformStatementId=row["platform_statement_id"],
        orderId=item.order_id,
        orderNumber=row["order_number"],
        orderPath=f"/orders/{item.order_id}" if item.order_id else None,
        platformOrderId=item.platform_order_id,
        type=item.transaction_type,
        status=item.status,
        basis="estimated" if item.is_estimated else "settled",
        currency=item.currency,
        revenueAmountMinor=item.revenue_amount_minor,
        refundAmountMinor=item.refund_amount_minor,
        shippingAmountMinor=item.shipping_amount_minor,
        feeAmountMinor=item.fee_amount_minor,
        adjustmentAmountMinor=item.adjustment_amount_minor,
        settlementAmountMinor=item.settlement_amount_minor,
        expectedSettlementAmountMinor=identity.expected_amount_minor,
        identityDifferenceMinor=identity.difference_minor,
        identityStatus=identity.status,
        occurredAt=item.occurred_at,
        platformUpdatedAt=item.platform_updated_at,
        syncedAt=item.synced_at,
        dataCompleteness=item.data_completeness,
        components=[component_response(value) for value in row["components"]],
    )


def component_response(item):
    return FinanceComponentResponse(
        id=item.id,
        componentCode=item.component_code,
        componentCategory=item.component_category,
        amountMinor=item.amount_minor,
        currency=item.currency,
        platformSkuId=item.platform_sku_id,
        orderLineId=item.order_line_id,
        description=item.description,
    )


def statement_response(row):
    item = row["statement"]
    identity = statement_identity(
        revenue_amount_minor=item.revenue_amount_minor,
        fee_amount_minor=item.fee_amount_minor,
        adjustment_amount_minor=item.adjustment_amount_minor,
        settlement_amount_minor=item.settlement_amount_minor,
    )
    transactions = statement_transaction_reconciliation(
        statement_amount_minor=item.settlement_amount_minor,
        transaction_amount_minor=row["transaction_amount_minor"],
    )
    payments = payment_statement_reconciliation(
        payment_amount_minor=row["payment_amount_minor"],
        linked_statement_amount_minor=item.settlement_amount_minor,
    )
    status = (
        "matched"
        if not identity.difference_minor
        and not transactions.difference_minor
        and not payments.difference_minor
        else "mismatched"
    )
    return FinanceStatementResponse(
        id=item.id,
        shopId=item.shop_id,
        platformStatementId=item.platform_statement_id,
        status=item.status,
        paymentStatus=item.payment_status,
        currency=item.currency,
        revenueAmountMinor=item.revenue_amount_minor,
        feeAmountMinor=item.fee_amount_minor,
        adjustmentAmountMinor=item.adjustment_amount_minor,
        settlementAmountMinor=item.settlement_amount_minor,
        expectedSettlementAmountMinor=identity.expected_amount_minor,
        identityDifferenceMinor=identity.difference_minor,
        transactionCount=row["transaction_count"],
        transactionAmountMinor=row["transaction_amount_minor"],
        statementTransactionDifferenceMinor=transactions.difference_minor,
        paymentCount=row["payment_count"],
        paymentAmountMinor=row["payment_amount_minor"],
        paymentStatementDifferenceMinor=payments.difference_minor,
        recexample81340158=status,
        statementStartAt=item.statement_start_at,
        statementEndAt=item.statement_end_at,
        platformCreatedAt=item.platform_created_at,
        platformUpdatedAt=item.platform_updated_at,
        syncedAt=item.synced_at,
    )


def statement_detail_response(row):
    base = statement_response(row).model_dump()
    return FinanceStatementDetailResponse(
        **base,
        transactions=[transaction_response(item) for item in row["transactions"]],
        payments=[linked_payment_response(item) for item in row["payments"]],
    )


def linked_payment_response(item):
    return LinkedFinancePaymentResponse(
        id=item.id,
        platformPaymentId=item.platform_payment_id,
        status=item.status,
        currency=item.currency,
        paymentAmountMinor=item.payment_amount_minor,
        initiatedAt=item.initiated_at,
        paidAt=item.paid_at,
        bankReferenceMasked=item.bank_reference_masked,
    )


def payment_response(row):
    item = row["payment"]
    result = payment_statement_reconciliation(
        payment_amount_minor=item.payment_amount_minor,
        linked_statement_amount_minor=row["statement_amount_minor"],
    )
    return FinancePaymentResponse(
        **linked_payment_response(item).model_dump(),
        shopId=item.shop_id,
        statementCount=row["statement_count"],
        statementAmountMinor=row["statement_amount_minor"],
        differenceMinor=result.difference_minor,
        recexample81340158=result.status,
        platformUpdatedAt=item.platform_updated_at,
        syncedAt=item.synced_at,
    )


def reconciliation_item_response(item):
    return FinanceReconciliationItemResponse(
        kind=item["kind"],
        entityType=item["entity_type"],
        entityId=item["entity_id"],
        reference=item["reference"],
        currency=item["currency"],
        expectedAmountMinor=item["expected_amount_minor"],
        actualAmountMinor=item["actual_amount_minor"],
        differenceMinor=item["difference_minor"],
        severity=item["severity"],
        occurredAt=item["occurred_at"],
    )


def order_summary_response(row):
    order = row["order"]
    totals = [
        FinanceOrderCurrencySummaryResponse(
            currency=currency,
            transactionCount=value["transaction_count"],
            revenueAmountMinor=value["revenue_amount_minor"],
            feeAmountMinor=value["fee_amount_minor"],
            settlementAmountMinor=value["settlement_amount_minor"],
        )
        for currency, value in sorted(row["totals"].items())
    ]
    return FinanceOrderSummaryResponse(
        orderId=order.id,
        orderNumber=order.order_number,
        platformOrderId=order.platform_order_id,
        totals=totals,
        transactions=[transaction_response(item) for item in row["transactions"]],
    )
