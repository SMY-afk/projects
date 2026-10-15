import { useMutation, useQuery } from '@tanstack/react-query'
import { financeApi } from '../api/finance.api'
import type {
  FinanceExportResource,
  FinanceFilters,
  FinanceOverviewFilters,
  FinancePaymentListParams,
  FinanceReconciliationFilters,
  FinanceStatementListParams,
  FinanceSyncRequest,
  FinanceTransactionListParams,
} from '../types/finance.types'

export const FINANCE_AUTO_REFRESH_MS = 60_000

export const financeQueryKeys = {
  all: ['finance'] as const,
  shops: ['finance', 'shops'] as const,
  overview: (filters: FinanceOverviewFilters) => ['finance', 'overview', filters] as const,
  statements: (params: FinanceStatementListParams) => ['finance', 'statements', params] as const,
  statement: (statementId: string) => ['finance', 'statement', statementId] as const,
  transactions: (params: FinanceTransactionListParams) => ['finance', 'transactions', params] as const,
  transaction: (transactionId: string) => ['finance', 'transaction', transactionId] as const,
  payments: (params: FinancePaymentListParams) => ['finance', 'payments', params] as const,
  reconciliation: (filters: FinanceReconciliationFilters) => ['finance', 'reconciliation', filters] as const,
  orderSummary: (orderId: string) => ['finance', 'order-summary', orderId] as const,
}

export const useFinanceShopsQuery = () =>
  useQuery({ queryKey: financeQueryKeys.shops, queryFn: () => financeApi.listShops() })

export const useFinanceOverviewQuery = (filters: FinanceOverviewFilters, enabled = true) =>
  useQuery({
    queryKey: financeQueryKeys.overview(filters),
    queryFn: () => financeApi.overview(filters),
    enabled,
    refetchInterval: FINANCE_AUTO_REFRESH_MS,
  })

export const useFinanceStatementsQuery = (params: FinanceStatementListParams, enabled = true) =>
  useQuery({
    queryKey: financeQueryKeys.statements(params),
    queryFn: () => financeApi.statements(params),
    enabled,
    refetchInterval: FINANCE_AUTO_REFRESH_MS,
  })

export const useFinanceStatementQuery = (statementId: string) =>
  useQuery({
    queryKey: financeQueryKeys.statement(statementId),
    queryFn: () => financeApi.statement(statementId),
    enabled: Boolean(statementId),
  })

export const useFinanceTransactionsQuery = (params: FinanceTransactionListParams, enabled = true) =>
  useQuery({ queryKey: financeQueryKeys.transactions(params), queryFn: () => financeApi.transactions(params), enabled })

export const useFinanceTransactionQuery = (transactionId: string) =>
  useQuery({
    queryKey: financeQueryKeys.transaction(transactionId),
    queryFn: () => financeApi.transaction(transactionId),
    enabled: Boolean(transactionId),
  })

export const useFinancePaymentsQuery = (params: FinancePaymentListParams, enabled = true) =>
  useQuery({ queryKey: financeQueryKeys.payments(params), queryFn: () => financeApi.payments(params), enabled })

export const useFinanceReconciliationQuery = (filters: FinanceReconciliationFilters, enabled = true) =>
  useQuery({
    queryKey: financeQueryKeys.reconciliation(filters),
    queryFn: () => financeApi.reconciliation(filters),
    enabled,
  })

export const useFinanceOrderSummaryQuery = (orderId: string) =>
  useQuery({
    queryKey: financeQueryKeys.orderSummary(orderId),
    queryFn: () => financeApi.orderSummary(orderId),
    enabled: Boolean(orderId),
  })

export const useFinanceExportMutation = () =>
  useMutation({
    mutationFn: ({ resource, filters }: { resource: FinanceExportResource; filters: FinanceFilters }) =>
      financeApi.exportCsv(resource, filters),
  })

export const useFinanceSyncMutation = () =>
  useMutation({ mutationFn: (payload: FinanceSyncRequest) => financeApi.sync(payload) })
