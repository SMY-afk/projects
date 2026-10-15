import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

Object.defineProperty(globalThis, 'ResizeObserver', {
  writable: true,
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(() => ({
    matches: false,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

const mocks = vi.hoisted(() => ({
  overview: vi.fn(),
  shops: vi.fn(),
  statements: vi.fn(),
  exportMutation: vi.fn(),
}))

vi.mock('../queries/finance.queries', () => ({
  useFinanceOverviewQuery: mocks.overview,
  useFinanceShopsQuery: mocks.shops,
  useFinanceStatementsQuery: mocks.statements,
  useFinanceExportMutation: mocks.exportMutation,
}))
vi.mock('../api/finance.api', () => ({ isFinanceMock: false }))
vi.mock('../components/finance-trend-chart', () => ({
  FinanceTrendChart: () => <div>每日金额趋势图</div>,
}))
vi.mock('../components/finance-fee-chart', () => ({
  FinanceFeeChart: () => <div>费用构成图</div>,
}))

import FinanceOverviewPage from './finance-overview-page'

const item = {
  period: { from: '2026-08-01T00:00:00Z', to: '2026-08-21T00:00:00Z' },
  currency: 'USD',
  basis: 'mixed',
  grossRevenueMinor: 10_000,
  refundAmountMinor: -500,
  platformFeeMinor: -800,
  affiliateCommissionMinor: -200,
  shippingAmountMinor: 300,
  taxAmountMinor: 0,
  adjustmentAmountMinor: 0,
  settlementAmountMinor: 8_800,
  paidAmountMinor: 8_500,
  outstandingAmountMinor: 300,
  statementTransactionDifferenceMinor: 0,
  paymentStatementDifferenceMinor: -300,
  contributionProfitMinor: null,
  marginBps: null,
  completeness: 'partial',
  missingReasons: ['estimated_transactions_present', 'product_cost_unavailable'],
  trend: [
    {
      date: '2026-08-20T00:00:00Z',
      revenueAmountMinor: 10_000,
      refundAmountMinor: -500,
      feeAmountMinor: -1_000,
      settlementAmountMinor: 8_800,
    },
  ],
} as const

describe('Finance overview page', () => {
  beforeEach(() => {
    mocks.shops.mockReturnValue({
      data: [{ id: 'shop-1', shopName: 'Akeleo Fun Toys', timezone: 'America/Los_Angeles' }],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    mocks.overview.mockReturnValue({ data: { items: [item] }, isLoading: false, isError: false, refetch: vi.fn() })
    mocks.statements.mockReturnValue({
      data: {
        items: [
          {
            id: 'statement-1',
            platformStatementId: 'platform-statement-1',
            statementStartAt: '2026-08-14T00:00:00Z',
            statementEndAt: '2026-08-20T00:00:00Z',
            currency: 'USD',
            settlementAmountMinor: 8_800,
            paymentStatus: 'PROCESSING',
            recexample81340158: 'matched',
            statementTransactionDifferenceMinor: 0,
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
    mocks.exportMutation.mockReturnValue({ mutate: vi.fn(), isPending: false })
  })

  it('renders filters, KPI, charts, recent statements and completeness warning', () => {
    render(
      <MemoryRouter>
        <FinanceOverviewPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '财务总览' })).toBeInTheDocument()
    expect(screen.getByLabelText('财务店铺')).toBeInTheDocument()
    expect(screen.getByText('销售收入')).toBeInTheDocument()
    expect(screen.getAllByText('结算金额').length).toBeGreaterThan(0)
    expect(screen.getByText('每日金额趋势图')).toBeInTheDocument()
    expect(screen.getByText('费用构成图')).toBeInTheDocument()
    expect(screen.getByText('platform-statement-1')).toBeInTheDocument()
    expect(screen.getByText('付款中')).toBeInTheDocument()
    expect(screen.queryByText('PROCESSING')).not.toBeInTheDocument()
    expect(screen.getByText('数据部分完整')).toBeInTheDocument()
    expect(screen.queryByText('真实 API')).not.toBeInTheDocument()
  })
})
