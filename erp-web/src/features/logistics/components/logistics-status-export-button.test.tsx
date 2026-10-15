import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { LogisticsStatusExportButton } from './logistics-status-export-button'
import { liveFixture } from '../utils/logistics-status-test-fixture'

const mocks = vi.hoisted(() => ({ exportOrders: vi.fn(), refresh: vi.fn(), build: vi.fn(), save: vi.fn(), request: vi.fn() }))
vi.mock('@/services/http-client', () => ({ request: mocks.request }))
vi.mock('../api/logistics-status.api', () => ({
  logisticsStatusApi: { exportOrders: mocks.exportOrders, refresh: mocks.refresh },
}))
vi.mock('../utils/logistics-status-export', () => ({
  buildLogisticsStatusExcel: mocks.build,
  saveLogisticsStatusExcel: mocks.save,
}))

describe('logistics export button', () => {
  it('exports all filtered orders and passes the live results to the workbook', async () => {
    mocks.request.mockResolvedValue([{ id: 'shop-1', timezone: 'America/Los_Angeles' }])
    mocks.exportOrders.mockResolvedValue({ items: [{ id: 'order-1', shopId: 'shop-1' }, { id: 'order-2', shopId: 'shop-1' }], total: 2 })
    mocks.build.mockResolvedValue({ blob: new Blob(), fileName: 'status.xlsx' })
    mocks.refresh.mockImplementation((id: string) => Promise.resolve({ ...liveFixture, orderId: id }))
    render(<LogisticsStatusExportButton shopId="shop-1" shopName="Shop" orderNumber="982740775181726442" alert="undelivered_77h" />)
    fireEvent.click(screen.getByRole('button', { name: '导出 Excel（当前筛选全部订单）' }))
    await waitFor(() => expect(mocks.save).toHaveBeenCalledOnce())
    expect(mocks.exportOrders).toHaveBeenCalledWith(
      { shopId: 'shop-1', orderNumber: '982740775181726442', category: undefined, alert: 'undelivered_77h', alertPhase: undefined },
      expect.any(AbortSignal),
    )
    expect(mocks.build).toHaveBeenCalledWith(
      [{ id: 'order-1', shopId: 'shop-1' }, { id: 'order-2', shopId: 'shop-1' }],
      { 'order-1': liveFixture, 'order-2': { ...liveFixture, orderId: 'order-2' } },
      'Shop · 订单982740775181726442',
      {},
      { 'shop-1': 'America/Los_Angeles' },
    )
    expect(mocks.refresh).toHaveBeenCalledTimes(2)
  })
})
