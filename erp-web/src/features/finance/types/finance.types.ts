export type FinanceBasis = 'settled' | 'estimated' | 'mixed' | 'unavailable'
export type FinanceCompleteness = 'complete' | 'partial' | 'unavailable'
export type FinanceReconciliationStatus = 'matched' | 'mismatched'
export type FinanceExportResource = 'statements' | 'transactions' | 'payments'
export type FinanceOrderPaymentState = 'completed' | 'refunded' | 'pending'

export interface FinanceFilters {
  shopId?: string
  from?: string
  to?: string
  currency?: string
}

export interface FinanceOverviewFilters extends FinanceFilters {
  isEstimated?: boolean
}

export interface FinanceReconciliationFilters extends FinanceFilters {
  status?: string
}

export interface FinancePageParams extends FinanceFilters {
  page: number
  pageSize: number
  status?: string
}

export interface FinanceStatementListParams extends FinancePageParams {
  paymentStatus?: string
}

export interface FinanceTransactionListParams extends FinancePageParams {
  statementId?: string
  orderId?: string
  type?: string
  isEstimated?: boolean
  paymentState?: FinanceOrderPaymentState
  keyword?: string
}

export type FinancePaymentListParams = FinancePageParams

export interface FinancePage<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}

export interface FinanceOverviewPeriod {
  from: string | null
  to: string | null
}

export interface FinanceOverviewItem {
  period: FinanceOverviewPeriod
  currency: string
  basis: FinanceBasis
  grossRevenueMinor: number
  refundAmountMinor: number
  platformFeeMinor: number
  affiliateCommissionMinor: number
  shippingAmountMinor: number
  taxAmountMinor: number
  adjustmentAmountMinor: number
  settlementAmountMinor: number
  paidAmountMinor: number
  outstandingAmountMinor: number
  statementTransactionDifferenceMinor: number
  paymentStatementDifferenceMinor: number
  contributionProfitMinor: number | null
  marginBps: number | null
  completeness: FinanceCompleteness
  missingReasons: string[]
  trend: FinanceTrendPoint[]
}

export interface FinanceTrendPoint {
  date: string
  revenueAmountMinor: number
  refundAmountMinor: number
  feeAmountMinor: number
  settlementAmountMinor: number
}

export interface FinanceOverviewResult {
  items: FinanceOverviewItem[]
}

export interface FinanceComponent {
  id: string
  componentCode: string
  componentCategory: string
  amountMinor: number
  currency: string
  platformSkuId: string | null
  orderLineId: string | null
  description: string | null
}

export interface FinanceTransaction {
  id: string
  shopId: string
  platformTransactionId: string | null
  statementId: string | null
  platformStatementId: string | null
  orderId: string | null
  orderNumber: string | null
  orderPath: string | null
  platformOrderId: string | null
  type: string
  status: string
  basis: Exclude<FinanceBasis, 'mixed' | 'unavailable'>
  currency: string
  revenueAmountMinor: number
  refundAmountMinor: number
  shippingAmountMinor: number
  feeAmountMinor: number
  adjustmentAmountMinor: number
  settlementAmountMinor: number
  expectedSettlementAmountMinor: number
  identityDifferenceMinor: number
  identityStatus: FinanceReconciliationStatus
  occurredAt: string
  platformUpdatedAt: string | null
  syncedAt: string
  dataCompleteness: string
  components: FinanceComponent[]
}

export interface FinanceStatement {
  id: string
  shopId: string
  platformStatementId: string
  status: string
  paymentStatus: string
  currency: string
  revenueAmountMinor: number
  feeAmountMinor: number
  adjustmentAmountMinor: number
  settlementAmountMinor: number
  expectedSettlementAmountMinor: number
  identityDifferenceMinor: number
  transactionCount: number
  transactionAmountMinor: number
  statementTransactionDifferenceMinor: number
  paymentCount: number
  paymentAmountMinor: number
  paymentStatementDifferenceMinor: number
  recexample81340158: FinanceReconciliationStatus
  statementStartAt: string
  statementEndAt: string
  platformCreatedAt: string
  platformUpdatedAt: string | null
  syncedAt: string
}

export interface FinanceLinkedPayment {
  id: string
  platformPaymentId: string
  status: string
  currency: string
  paymentAmountMinor: number
  initiatedAt: string
  paidAt: string | null
  bankReferenceMasked: string | null
}

export interface FinanceStatementDetail extends FinanceStatement {
  transactions: FinanceTransaction[]
  payments: FinanceLinkedPayment[]
}

export interface FinancePayment extends FinanceLinkedPayment {
  shopId: string
  statementCount: number
  statementAmountMinor: number
  differenceMinor: number
  recexample81340158: FinanceReconciliationStatus
  platformUpdatedAt: string | null
  syncedAt: string
}

export interface FinanceReconciliationItem {
  kind: string
  entityType: string
  entityId: string
  reference: string
  currency: string
  expectedAmountMinor: number
  actualAmountMinor: number
  differenceMinor: number
  severity: string
  occurredAt: string
}

export interface FinanceReconciliationResult {
  items: FinanceReconciliationItem[]
  total: number
  limit: number
}

export interface FinanceOrderCurrencySummary {
  currency: string
  transactionCount: number
  revenueAmountMinor: number
  feeAmountMinor: number
  settlementAmountMinor: number
}

export interface FinanceOrderSummary {
  orderId: string
  orderNumber: string
  platformOrderId: string
  totals: FinanceOrderCurrencySummary[]
  transactions: FinanceTransaction[]
}

export interface FinanceShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
  timezone?: string | null
}

export interface FinanceSyncRequest {
  shopId: string
  mode: 'backfill' | 'incremental'
  from?: string
  to?: string
}

export interface FinanceSyncResult {
  runId: string
  shopId: string
  status: string
  fetchedCount: number
  writtenCount: number
  recoveryCursor: string | null
  error: string | null
}
