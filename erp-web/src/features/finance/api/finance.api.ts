import { isFinanceMockEnabled } from '@/services/api-mode'
import { downloadFile, request, type DownloadFile } from '@/services/http-client'
import { mockFinanceApi } from './mock-finance-api'
import type {
  FinanceExportResource,
  FinanceFilters,
  FinanceOrderSummary,
  FinanceOverviewFilters,
  FinanceOverviewResult,
  FinancePage,
  FinancePayment,
  FinancePaymentListParams,
  FinanceReconciliationResult,
  FinanceReconciliationFilters,
  FinanceShopOption,
  FinanceStatement,
  FinanceStatementDetail,
  FinanceStatementListParams,
  FinanceSyncRequest,
  FinanceSyncResult,
  FinanceTransaction,
  FinanceTransactionListParams,
} from '../types/finance.types'

export interface FinanceApi {
  listShops(): Promise<FinanceShopOption[]>
  overview(filters: FinanceOverviewFilters): Promise<FinanceOverviewResult>
  statements(params: FinanceStatementListParams): Promise<FinancePage<FinanceStatement>>
  statement(statementId: string): Promise<FinanceStatementDetail>
  transactions(params: FinanceTransactionListParams): Promise<FinancePage<FinanceTransaction>>
  transaction(transactionId: string): Promise<FinanceTransaction>
  payments(params: FinancePaymentListParams): Promise<FinancePage<FinancePayment>>
  reconciliation(filters: FinanceReconciliationFilters): Promise<FinanceReconciliationResult>
  orderSummary(orderId: string): Promise<FinanceOrderSummary>
  exportCsv(resource: FinanceExportResource, filters: FinanceFilters): Promise<DownloadFile>
  sync(payload: FinanceSyncRequest): Promise<FinanceSyncResult>
}

const httpFinanceApi: FinanceApi = {
  listShops: () => request<FinanceShopOption[]>({ method: 'get', url: '/shops' }),
  overview: (params) => request<FinanceOverviewResult>({ method: 'get', url: '/finance/overview', params }),
  statements: (params) => request<FinancePage<FinanceStatement>>({ method: 'get', url: '/finance/statements', params }),
  statement: (statementId) =>
    request<FinanceStatementDetail>({ method: 'get', url: `/finance/statements/${statementId}` }),
  transactions: (params) =>
    request<FinancePage<FinanceTransaction>>({ method: 'get', url: '/finance/transactions', params }),
  transaction: (transactionId) =>
    request<FinanceTransaction>({ method: 'get', url: `/finance/transactions/${transactionId}` }),
  payments: (params) => request<FinancePage<FinancePayment>>({ method: 'get', url: '/finance/payments', params }),
  reconciliation: (params) =>
    request<FinanceReconciliationResult>({ method: 'get', url: '/finance/reconciliation', params }),
  orderSummary: (orderId) => request<FinanceOrderSummary>({ method: 'get', url: `/finance/orders/${orderId}/summary` }),
  exportCsv: (resource, filters) =>
    downloadFile('/finance/export', { method: 'get', params: { resource, ...filters } }),
  sync: (data) => request<FinanceSyncResult>({ method: 'post', url: '/finance/sync', data }),
}

export const isFinanceMock = isFinanceMockEnabled()
export const financeApi: FinanceApi = isFinanceMock ? mockFinanceApi : httpFinanceApi
