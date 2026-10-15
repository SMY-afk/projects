import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OrderListParams } from '../types/order.types'
import OrderListPage from './order-list-page'

const mocks = vi.hoisted(() => ({
  useOrderListQuery: vi.fn(),
  useOrderShopOptionsQuery: vi.fn(),
}))

vi.mock('../queries/order.queries', () => mocks)
vi.mock('../components/order-list', () => ({
  OrderList: ({ onSearchChange }: { onSearchChange: (value: string) => void }) => (
    <input aria-label="订单搜索" onChange={(event) => onSearchChange(event.target.value)} />
  ),
}))

afterEach(() => {
  vi.useRealTimers()
  mocks.useOrderListQuery.mockReset()
  mocks.useOrderShopOptionsQuery.mockReset()
})

describe('OrderListPage search', () => {
  it('applies only the settled search text and keeps the input mounted', () => {
    vi.useFakeTimers()
    const requested: OrderListParams[] = []
    mocks.useOrderListQuery.mockImplementation((params: OrderListParams) => {
      requested.push(params)
      return {
        data: { items: [], page: 1, pageSize: 20, total: 0 },
        isLoading: false,
        isError: false,
      }
    })
    mocks.useOrderShopOptionsQuery.mockReturnValue({ data: [] })

    render(
      <MemoryRouter>
        <OrderListPage />
      </MemoryRouter>,
    )
    const search = screen.getByRole('textbox', { name: '订单搜索' })
    fireEvent.change(search, { target: { value: 'T' } })
    fireEvent.change(search, { target: { value: 'TT' } })
    fireEvent.change(search, { target: { value: 'TT-1' } })

    expect(requested.every((params) => params.keyword === undefined)).toBe(true)
    act(() => {
      vi.advanceTimersByTime(400)
    })
    expect(requested.at(-1)?.keyword).toBe('TT-1')
    expect(requested.filter((params) => params.keyword)).toHaveLength(1)
    expect(screen.getByRole('textbox', { name: '订单搜索' })).toBe(search)
  })
})
