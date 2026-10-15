import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import LogisticsStatusPage from './logistics-status-page'
import type { LogisticsStatusList, LogisticsStatusLive } from '../types/logistics-status.types'
import { liveFixture } from '../utils/logistics-status-test-fixture'

const mocks = vi.hoisted(() => ({
  list: vi.fn<
    (params?: { page: number; pageSize: number; shopId?: string; orderNumber?: string }) => Promise<LogisticsStatusList>
  >(),
  refresh: vi.fn<(orderId: string) => Promise<LogisticsStatusLive>>(),
  sync: vi.fn(),
}))

vi.mock('../api/logistics-status.api', () => ({
  logisticsStatusApi: mocks,
}))
vi.mock('../queries/logistics.queries', () => ({
  useLogisticsShopOptionsQuery: () => ({ data: [], isLoading: false }),
}))
vi.mock('@/auth/use-auth', () => ({ useAuth: () => ({ hasPermissions: () => false }) }))
vi.mock('../components/logistics-section-nav', () => ({
  LogisticsSectionNav: () => <nav>物流导航</nav>,
}))

describe('LogisticsStatusPage', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
  })

  beforeEach(() => {
    mocks.list.mockReset()
    mocks.refresh.mockReset()
    mocks.sync.mockReset()
    mocks.sync.mockImplementation((params: Parameters<typeof mocks.list>[0]) => mocks.list(params))
    mocks.list.mockResolvedValue({
      items: [
        {
          id: 'order-1',
          shopId: 'shop-1',
          shopName: 'Akeleo Toys',
          orderNumber: 'ORDER-1',
          orderCreatedAt: '2026-10-07T08:52:41Z',
          platformStatus: 'IN_TRANSIT',
          shippingType: 'SELLER',
          platformUpdatedAt: '2026-10-09T02:19:18Z',
          erpSyncedAt: '2026-10-09T02:20:00Z',
          packages: [],
        },
      ],
      total: 1,
      page: 1,
      pageSize: 20,
    })
    mocks.refresh.mockResolvedValue({
      ...liveFixture,
      orderId: 'order-1',
      trackingStatus: 'delivered',
      shippingType: 'TIKTOK',
      fulfillmentType: 'FULFILLMENT_BY_TIKTOK',
      checkedAt: '2026-10-12T05:50:50Z',
      events: [],
      packages: [],
    })
  })

  it('queries official status for one selected shipped order', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <LogisticsStatusPage />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('ORDER-1')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '物流方式' })).toBeInTheDocument()
    expect(screen.getByText('商家物流')).toBeInTheDocument()
    expect(screen.getByText('待查询')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看物流' }))
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledOnce())
    expect(mocks.refresh).toHaveBeenCalledWith('order-1')
    expect(await screen.findByText('查看物流')).toBeInTheDocument()
    expect(await screen.findByText('FBT物流')).toBeInTheDocument()
    expect(screen.getByText('最新轨迹：已送达')).toBeInTheDocument()
  })

  it('reads background results and displays separate write/query times with frozen delivery duration', async () => {
    const data = await mocks.list()
    Object.assign(data.items[0], {
      platformStatus: 'COMPLETED',
      deliveredAt: '2026-10-10T17:04:00Z',
      erpSyncedAt: '2026-10-12T09:30:00Z',
      officialCheckedAt: '2026-10-12T09:29:00Z',
      officialTrackingStatus: 'delivered',
    })
    mocks.list.mockResolvedValue(data)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <LogisticsStatusPage />
      </QueryClientProvider>,
    )
    await screen.findByText('ORDER-1')
    expect(mocks.list).toHaveBeenCalledWith(expect.objectContaining({ page: 1, category: 'pending_shipment' }))
    expect(mocks.sync).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '立即同步' })).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'ERP同步时间' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '官方查询时间' })).toBeInTheDocument()
    expect(screen.queryByText('同步/查询时间')).not.toBeInTheDocument()
    expect(screen.getByText('2026/10/12 17:30:00')).toBeInTheDocument()
    expect(screen.getByText('2026/10/12 17:29:00')).toBeInTheDocument()
    expect(screen.getByText('3天 8小时 11分钟')).toBeInTheDocument()
  })

  it('shows an empty official result instead of an older cached status', async () => {
    const list = await mocks.list()
    list.items[0].packages = [
      {
        packageId: 'package-1',
        carrierName: 'Carrier',
        trackingNumberMasked: '****1234',
        trackingStatus: 'delivered',
        packageStatus: 'COMPLETED',
      },
    ]
    mocks.list.mockResolvedValue(list)
    mocks.refresh.mockResolvedValue({
      ...liveFixture,
      orderId: 'order-1',
      trackingStatus: null,
      checkedAt: '2026-10-12T05:50:50Z',
      events: [],
      packages: [],
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <LogisticsStatusPage />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('已送达')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看物流' }))
    expect(await screen.findByText('官方暂无轨迹')).toBeInTheDocument()
  })

  it('keeps the background sync time independent of manual queries and later polling', async () => {
    const data = await mocks.list()
    data.items[0].erpSyncedAt = '2026-10-12T09:30:00Z'
    mocks.list.mockResolvedValue(data)
    mocks.refresh.mockResolvedValue({ ...liveFixture, orderId: 'order-1',
      checkedAt: '2026-10-12T09:31:00Z', erpSyncedAt: '2026-10-12T09:29:00Z' })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><LogisticsStatusPage /></QueryClientProvider>)
    await screen.findByText('ORDER-1')
    fireEvent.click(screen.getByRole('button', { name: '查看物流' }))
    await screen.findByText('最新轨迹：已送达')
    const row = screen.getByText('ORDER-1').closest('tr')!
    expect(within(row).getByText('2026/10/12 17:30:00')).toBeInTheDocument()
    mocks.list.mockResolvedValue({ ...data, items: [{ ...data.items[0], erpSyncedAt: '2026-10-12T09:45:00Z' }] })
    await act(() => client.invalidateQueries({ queryKey: ['logistics', 'status'] }))
    await waitFor(() => expect(within(row).getByText('2026/10/12 17:45:00')).toBeInTheDocument())
    expect(screen.getByText('ERP同步时间：2026/10/12 17:45:00')).toBeInTheDocument()
    expect(within(row).getByText('2026/10/12 17:31:00')).toBeInTheDocument()
  })

  it('searches the complete order number, resets pagination, and clears the filter', async () => {
    const data = await mocks.list()
    mocks.list.mockResolvedValue({ ...data, total: 40 })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <LogisticsStatusPage />
      </QueryClientProvider>,
    )
    await screen.findByText('ORDER-1')
    fireEvent.click(screen.getByTitle('2'))
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith({
        page: 2,
        pageSize: 20,
        shopId: undefined,
        orderNumber: undefined,
        category: 'pending_shipment',
        alert: undefined,
        alertPhase: undefined,
      }),
    )
    fireEvent.change(screen.getByRole('searchbox', { name: '订单号查询' }), {
      target: { value: ' 982740775181726442 ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /查\s*询/ }))
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith({
        page: 1,
        pageSize: 20,
        shopId: undefined,
        orderNumber: '982740775181726442',
        category: 'pending_shipment',
        alert: undefined,
        alertPhase: undefined,
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: /重\s*置/ }))
    expect(screen.getByRole('searchbox', { name: '订单号查询' })).toHaveValue('')
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith({
        page: 1,
        pageSize: 20,
        shopId: undefined,
        orderNumber: undefined,
        category: 'pending_shipment',
        alert: undefined,
        alertPhase: undefined,
      }),
    )
  })

  it('switches server categories, resets pagination and marks partial shipping separately', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <LogisticsStatusPage />
      </QueryClientProvider>,
    )
    await screen.findByText('ORDER-1')
    expect(screen.getAllByRole('tab')).toHaveLength(5)
    fireEvent.click(screen.getByRole('tab', { name: /已送达/ }))
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'delivered', page: 1 })),
    )
    expect(screen.queryByText(/按下单时间显示最近三个月/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /部分发货/ }))
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'partial_shipping', page: 1 })),
    )
    expect(screen.getByText('特殊情况：部分发货')).toBeInTheDocument()
  })

  it('uses backend warning counts and switches from a category into longest overdue results', async () => {
    const data = await mocks.list()
    mocks.list.mockResolvedValue({ ...data, warnings: {
      cards: [
        { key: 'unshipped_48h', thresholdHours: 48, upcomingCount: 1, overdueCount: 3, closestRemainingSeconds: 7200, longestOverdueSeconds: 86400 },
        { key: 'uncollected_48h', thresholdHours: 48, upcomingCount: 2, overdueCount: 4, closestRemainingSeconds: 7200, longestOverdueSeconds: 90000 },
        { key: 'undelivered_77h', thresholdHours: 77, upcomingCount: 3, overdueCount: 5, closestRemainingSeconds: 7200, longestOverdueSeconds: 180000 },
      ], uniqueOrderCount: 6, upcomingUniqueOrderCount: 3, overdueUniqueOrderCount: 6, leadHours: 3, asOf: '2026-10-12T09:31:00Z', lastDataSyncAt: '2026-10-12T09:30:00Z',
    } })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><LogisticsStatusPage /></QueryClientProvider>)
    await screen.findByText('ORDER-1')
    expect(screen.queryByText(/活动预警订单总数（去重）/)).not.toBeInTheDocument()
    expect(screen.queryByText(/当前分类不限下单时间/)).not.toBeInTheDocument()
    const card = screen.getByRole('button', { name: '未送达预警（77小时）：已超时订单' })
    expect(card).toHaveTextContent('5 单')
    fireEvent.click(card)
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({
      page: 1, alert: 'undelivered_77h', alertPhase: 'overdue', category: undefined,
    })))
    expect(screen.getByRole('columnheader', { name: '超时时长（最长优先）' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '未送达预警（77小时）：已超时订单' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(screen.getByRole('button', { name: '未送达预警（77小时）：快超时订单' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '未送达预警（77小时）：快超时订单' }))
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({
      alert: 'undelivered_77h', alertPhase: 'upcoming', category: undefined, page: 1,
    })))
    expect(screen.getByRole('columnheader', { name: '剩余时间（最紧急优先）' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /待揽收/ }))
    await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({
      category: 'pending_collection', alert: undefined,
    })))
  })

})
