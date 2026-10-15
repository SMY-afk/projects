import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { normalizeOrderDetail, normalizeOrderListResult, orderApi } from '../api/order.api'
import type { OrderListParams } from '../types/order.types'
import { orderQueryKeys, useOrderListQuery } from './order.queries'

describe('useOrderListQuery', () => {
  it('loads paginated orders with every filter in the module query key', async () => {
    const params: OrderListParams = {
      page: 2,
      pageSize: 20,
      shopId: 'shop-1',
      keyword: 'TT-1',
      status: 'awaiting_shipment',
      updatedFrom: '2026-08-01T00:00:00Z',
      updatedTo: '2026-08-02T00:00:00Z',
      contentForm: 'video',
    }
    const response = { items: [], total: 0, page: 2, pageSize: 20 }
    const getList = vi.spyOn(orderApi, 'getList').mockResolvedValue(response)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useOrderListQuery(params), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(getList).toHaveBeenCalledWith(params, expect.any(AbortSignal))
    expect(queryClient.getQueryData(orderQueryKeys.list(params))).toEqual(response)
    getList.mockRestore()
  })

  it('passes a cancellable signal to the list request', async () => {
    const params: OrderListParams = { page: 1, pageSize: 20 }
    const getList = vi.spyOn(orderApi, 'getList').mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useOrderListQuery(params), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(getList).toHaveBeenCalledWith(params, expect.any(AbortSignal))
    getList.mockRestore()
  })

  it('keeps the current list visible while the next filter request is pending', async () => {
    const current = { items: [], total: 1, page: 1, pageSize: 20 }
    const getList = vi
      .spyOn(orderApi, 'getList')
      .mockImplementation((params) =>
        params.keyword ? new Promise<typeof current>(() => undefined) : Promise.resolve(current),
      )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result, rerender } = renderHook(({ keyword }) => useOrderListQuery({ page: 1, pageSize: 20, keyword }), {
      initialProps: { keyword: undefined as string | undefined },
      wrapper,
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    rerender({ keyword: 'TT-1' })
    expect(result.current.data).toEqual(current)
    expect(result.current.isPlaceholderData).toBe(true)
    getList.mockRestore()
  })

  it('aborts the superseded list request', () => {
    const getList = vi
      .spyOn(orderApi, 'getList')
      .mockImplementation(() => new Promise<Awaited<ReturnType<typeof orderApi.getList>>>(() => undefined))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { rerender } = renderHook(({ keyword }) => useOrderListQuery({ page: 1, pageSize: 20, keyword }), {
      initialProps: { keyword: 'first' },
      wrapper,
    })
    const firstSignal = getList.mock.calls[0][1]
    rerender({ keyword: 'second' })
    expect(firstSignal?.aborted).toBe(true)
    getList.mockRestore()
  })
})

describe('order response normalization', () => {
  it('keeps orders renderable when the backend omits attribution', () => {
    const result = normalizeOrderListResult({
      items: [{ attribution: undefined, orderNumber: 'order-1' } as never],
      total: 1,
      page: 1,
      pageSize: 20,
    })

    expect(result.items[0].attribution).toEqual({
      trafficSource: 'unknown',
      operatorSubject: 'unknown',
      entryPoint: 'unknown',
      specialOrderType: 'unknown',
      chainCode: 'unknown',
      classificationStatus: 'unknown',
    })
    expect(result.items[0].affiliateItems).toEqual([])
  })

  it('keeps order detail renderable when the backend omits attribution', () => {
    const detail = normalizeOrderDetail({ attribution: undefined } as never)

    expect(detail.attribution.chainCode).toBe('unknown')
    expect(detail.attribution.classificationMethod).toBe('shop_order_detail')
    expect(detail.attribution.evidenceSummary).toEqual([])
    expect(detail.affiliateItems).toEqual([])
  })
})
