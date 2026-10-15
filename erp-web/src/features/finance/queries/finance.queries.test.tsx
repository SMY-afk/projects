import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { financeApi } from '../api/finance.api'
import type { FinanceTransactionListParams } from '../types/finance.types'
import {
  FINANCE_AUTO_REFRESH_MS,
  financeQueryKeys,
  useFinanceOverviewQuery,
  useFinanceStatementsQuery,
  useFinanceTransactionsQuery,
} from './finance.queries'

describe('Finance Query Keys', () => {
  it('keeps every transaction filter in the server-side list key', async () => {
    const params: FinanceTransactionListParams = {
      page: 2,
      pageSize: 50,
      shopId: 'shop-1',
      statementId: 'statement-1',
      orderId: 'order-1',
      type: 'order',
      status: 'settled',
      isEstimated: false,
      keyword: 'TT-1',
      from: '2026-08-01T00:00:00Z',
      to: '2026-08-21T00:00:00Z',
      currency: 'USD',
    }
    const response = { items: [], total: 0, page: 2, pageSize: 50 }
    const request = vi.spyOn(financeApi, 'transactions').mockResolvedValue(response)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useFinanceTransactionsQuery(params), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(request).toHaveBeenCalledWith(params)
    expect(financeQueryKeys.transactions(params)).toEqual(['finance', 'transactions', params])
    expect(queryClient.getQueryData(financeQueryKeys.transactions(params))).toEqual(response)
    request.mockRestore()
  })

  it('uses independent keys for every Finance resource and detail', () => {
    const filters = { shopId: 'shop-1', from: '2026-08-01T00:00:00Z', to: '2026-08-21T00:00:00Z' }

    expect(financeQueryKeys.overview(filters)).toEqual(['finance', 'overview', filters])
    expect(financeQueryKeys.statements({ ...filters, page: 1, pageSize: 20 })).toEqual([
      'finance',
      'statements',
      { ...filters, page: 1, pageSize: 20 },
    ])
    expect(financeQueryKeys.statement('statement-1')).toEqual(['finance', 'statement', 'statement-1'])
    expect(financeQueryKeys.transaction('transaction-1')).toEqual(['finance', 'transaction', 'transaction-1'])
    expect(financeQueryKeys.payments({ ...filters, page: 1, pageSize: 20 })).toEqual([
      'finance',
      'payments',
      { ...filters, page: 1, pageSize: 20 },
    ])
    expect(financeQueryKeys.reconciliation(filters)).toEqual(['finance', 'reconciliation', filters])
    expect(financeQueryKeys.orderSummary('order-1')).toEqual(['finance', 'order-summary', 'order-1'])
  })

  it('polls overview and recent statements every minute', async () => {
    const filters = { shopId: 'shop-1', currency: 'USD' }
    const statementParams = { ...filters, page: 1, pageSize: 5 }
    const overviewRequest = vi.spyOn(financeApi, 'overview').mockResolvedValue({ items: [] })
    const statementsRequest = vi
      .spyOn(financeApi, 'statements')
      .mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 5 })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    renderHook(
      () => {
        useFinanceOverviewQuery(filters)
        useFinanceStatementsQuery(statementParams)
      },
      { wrapper },
    )

    await waitFor(() => expect(overviewRequest).toHaveBeenCalled())
    await waitFor(() => expect(statementsRequest).toHaveBeenCalled())
    expect(FINANCE_AUTO_REFRESH_MS).toBe(60_000)
    overviewRequest.mockRestore()
    statementsRequest.mockRestore()
  })
})
