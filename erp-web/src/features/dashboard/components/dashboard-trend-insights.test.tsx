import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DashboardQueryParams, DashboardSnapshot } from '../types/dashboard.types'
import { DashboardTrendInsights } from './dashboard-trend-insights'

const params: DashboardQueryParams = {
  currency: 'USD',
  timezone: 'America/Los_Angeles',
  realtimeRange: 'today',
  trendRange: 'last30d',
  orderRange: 'last28d',
}

const summary = {
  salesVolume: 120,
  orderCount: 80,
  salesAmountMinor: 240000,
  netSalesAmountMinor: 210000,
  averageItemPriceMinor: 2000,
  cancelledOrderCount: 4,
}

const snapshot: DashboardSnapshot = {
  generatedAt: '2026-09-21T00:00:00Z',
  filters: { platforms: [], sites: [], shops: [], currencies: ['USD'] },
  selection: params,
  realtime: { period: { start: '', end: '' }, current: summary, previous: summary, lastWeek: summary },
  trend: {
    period: { start: '2026-08-23T00:00:00Z', end: '2026-09-21T00:00:00Z' },
    current: summary,
    previous: { ...summary, orderCount: 70, salesVolume: 100, cancelledOrderCount: 6 },
    lastYear: summary,
    points: [
      { date: '2026-09-20', orderCount: 30, salesVolume: 42, salesAmountMinor: 80000, netSalesAmountMinor: 71000 },
      { date: '2026-09-21', orderCount: 50, salesVolume: 78, salesAmountMinor: 160000, netSalesAmountMinor: 139000 },
    ],
  },
  fulfilmentMetrics: [],
  salesDistribution: [],
  orderDistribution: [],
  productPerformance: [],
  affiliateOperations: {
    sampleFunnel: {
      scope: 'current_projection_all_time',
      applicationCount: 0,
      approvedCount: 0,
      shippedCount: 0,
      completedCount: 0,
      cancelledCount: 0,
      sourceObservedAt: null,
    },
    creatorLevels: [],
    creatorEfficiency: {
      period: null,
      complete: false,
      shopCount: 0,
      totalCreators: 0,
      totalGmvMinor: 0,
      rows: [],
      pareto: [],
    },
  },
  netSalesEstimated: true,
}

describe('DashboardTrendInsights', () => {
  it('renders truthful order metrics and switches performance trend mode', async () => {
    const user = userEvent.setup()
    render(<DashboardTrendInsights onChange={vi.fn()} params={params} snapshot={snapshot} />)

    expect(screen.getByText('订单与销售洞察')).toBeInTheDocument()
    expect(screen.getByText('经营表现趋势')).toBeInTheDocument()
    expect(screen.getByText('取消订单下降代表履约质量改善。')).toBeInTheDocument()

    const orderMode = screen.getByRole('button', { name: '销量 + 订单量' })
    await user.click(orderMode)
    expect(orderMode).toHaveClass('active')
    expect(screen.getAllByLabelText('订单销量趋势图')).toHaveLength(2)
  })
})
