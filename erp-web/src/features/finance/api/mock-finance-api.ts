import type { FinanceApi } from './finance.api'
import type {
  FinanceLinkedPayment,
  FinanceOrderPaymentState,
  FinancePayment,
  FinanceStatement,
  FinanceTransaction,
} from '../types/finance.types'

const stamp = '2026-08-20T08:00:00Z'
const shopId = 'b703c2aa-b855-5000-a01e-dc53f5086ec5'
const statementId = '715b02b1-3d49-55ce-b628-95d8ab58dba7'
const transactionId = '0c0d162e-1add-561a-96c5-a12715eca8eb'
const orderId = '49f5ebac-80cd-5ad4-a189-2f37bb91dc3b'

const transaction: FinanceTransaction = {
  id: transactionId,
  shopId,
  platformTransactionId: 'mock-transaction-1',
  statementId,
  platformStatementId: 'mock-statement-1',
  orderId,
  orderNumber: 'TT-US-MOCK-1',
  orderPath: `/orders/${orderId}`,
  platformOrderId: 'mock-order-1',
  type: 'order',
  status: 'settled',
  basis: 'settled',
  currency: 'USD',
  revenueAmountMinor: 10_000,
  refundAmountMinor: 0,
  shippingAmountMinor: 500,
  feeAmountMinor: -1_500,
  adjustmentAmountMinor: 0,
  settlementAmountMinor: 9_000,
  expectedSettlementAmountMinor: 9_000,
  identityDifferenceMinor: 0,
  identityStatus: 'matched',
  occurredAt: stamp,
  platformUpdatedAt: stamp,
  syncedAt: stamp,
  dataCompleteness: 'final',
  components: [],
}

const statement: FinanceStatement = {
  id: statementId,
  shopId,
  platformStatementId: 'mock-statement-1',
  status: 'available',
  paymentStatus: 'paid',
  currency: 'USD',
  revenueAmountMinor: 10_000,
  feeAmountMinor: -1_000,
  adjustmentAmountMinor: 0,
  settlementAmountMinor: 9_000,
  expectedSettlementAmountMinor: 9_000,
  identityDifferenceMinor: 0,
  transactionCount: 1,
  transactionAmountMinor: 9_000,
  statementTransactionDifferenceMinor: 0,
  paymentCount: 1,
  paymentAmountMinor: 9_000,
  paymentStatementDifferenceMinor: 0,
  recexample81340158: 'matched',
  statementStartAt: stamp,
  statementEndAt: stamp,
  platformCreatedAt: stamp,
  platformUpdatedAt: stamp,
  syncedAt: stamp,
}

const linkedPayment: FinanceLinkedPayment = {
  id: 'a6eae3b1-57e3-5dcd-a89d-09d4a6b71c8b',
  platformPaymentId: 'mock-payment-1',
  status: 'paid',
  currency: 'USD',
  paymentAmountMinor: 9_000,
  initiatedAt: stamp,
  paidAt: stamp,
  bankReferenceMasked: '****1234',
}

const payment: FinancePayment = {
  ...linkedPayment,
  shopId,
  statementCount: 1,
  statementAmountMinor: 9_000,
  differenceMinor: 0,
  recexample81340158: 'matched',
  platformUpdatedAt: stamp,
  syncedAt: stamp,
}

const page = <T>(items: T[], pageNumber: number, pageSize: number) => ({
  items: items.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
  total: items.length,
  page: pageNumber,
  pageSize,
})

const orderPaymentState = (item: FinanceTransaction): FinanceOrderPaymentState => {
  if (item.basis === 'estimated' || item.status.toUpperCase() === 'UNSETTLED') return 'pending'
  return item.refundAmountMinor !== 0 ? 'refunded' : 'completed'
}

export const mockFinanceApi: FinanceApi = {
  listShops: () =>
    Promise.resolve([{ id: shopId, shopName: 'Finance Mock Shop', platform: 'tiktok', platformShopId: 'mock-shop' }]),
  overview: (filters) =>
    Promise.resolve({
      items: [
        {
          period: { from: filters.from ?? null, to: filters.to ?? null },
          currency: filters.currency ?? 'USD',
          basis: 'settled',
          grossRevenueMinor: 10_000,
          refundAmountMinor: 0,
          platformFeeMinor: -800,
          affiliateCommissionMinor: -200,
          shippingAmountMinor: 500,
          taxAmountMinor: 0,
          adjustmentAmountMinor: 0,
          settlementAmountMinor: 9_000,
          paidAmountMinor: 9_000,
          outstandingAmountMinor: 0,
          statementTransactionDifferenceMinor: 0,
          paymentStatementDifferenceMinor: 0,
          contributionProfitMinor: null,
          marginBps: null,
          completeness: 'complete',
          missingReasons: ['product_cost_unavailable'],
          trend: [
            {
              date: stamp,
              revenueAmountMinor: 10_000,
              refundAmountMinor: 0,
              feeAmountMinor: -1_000,
              settlementAmountMinor: 9_000,
            },
          ],
        },
      ],
    }),
  statements: (params) => Promise.resolve(page([statement], params.page, params.pageSize)),
  statement: () => Promise.resolve({ ...statement, transactions: [transaction], payments: [linkedPayment] }),
  transactions: (params) => {
    const items = params.paymentState
      ? [transaction].filter((item) => orderPaymentState(item) === params.paymentState)
      : [transaction]
    return Promise.resolve(page(items, params.page, params.pageSize))
  },
  transaction: () => Promise.resolve(transaction),
  payments: (params) => Promise.resolve(page([payment], params.page, params.pageSize)),
  reconciliation: () => Promise.resolve({ items: [], total: 0, limit: 100 }),
  orderSummary: () =>
    Promise.resolve({
      orderId,
      orderNumber: 'TT-US-MOCK-1',
      platformOrderId: 'mock-order-1',
      totals: [
        {
          currency: 'USD',
          transactionCount: 1,
          revenueAmountMinor: 10_000,
          feeAmountMinor: -1_500,
          settlementAmountMinor: 9_000,
        },
      ],
      transactions: [transaction],
    }),
  exportCsv: (resource) =>
    Promise.resolve({
      blob: new Blob([`resource\r\n${resource}\r\n`], { type: 'text/csv;charset=utf-8' }),
      fileName: `finance-${resource}.csv`,
      contentType: 'text/csv;charset=utf-8',
    }),
  sync: (payload) =>
    Promise.resolve({
      runId: 'a28eeb3b-8d6e-5862-ab3a-b7a61769ee69',
      shopId: payload.shopId,
      status: 'succeeded',
      fetchedCount: 3,
      writtenCount: 3,
      recoveryCursor: null,
      error: null,
    }),
}
