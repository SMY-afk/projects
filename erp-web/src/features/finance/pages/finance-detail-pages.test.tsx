import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  shops: vi.fn(),
  statement: vi.fn(),
  transactions: vi.fn(),
}))

vi.mock('../queries/finance.queries', () => ({
  useFinanceShopsQuery: mocks.shops,
  useFinanceStatementQuery: mocks.statement,
  useFinanceTransactionsQuery: mocks.transactions,
}))
vi.mock('../api/finance.api', () => ({ isFinanceMock: false }))

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
  value: () => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  }),
})

import FinanceStatementDetailPage from './finance-statement-detail-page'
import FinanceOrdersPage from './finance-orders-page'
import FinanceTransactionsPage from './finance-transactions-page'

const transaction = {
  id: 'transaction-1',
  shopId: 'shop-1',
  platformTransactionId: 'platform-transaction-1',
  statementId: 'statement-1',
  platformStatementId: 'platform-statement-1',
  orderId: 'order-1',
  orderNumber: 'ERP-ORDER-1',
  orderPath: '/orders/order-1',
  platformOrderId: 'platform-order-1',
  type: 'order',
  status: 'settled',
  basis: 'settled',
  currency: 'USD',
  revenueAmountMinor: 10_000,
  refundAmountMinor: 0,
  shippingAmountMinor: 0,
  feeAmountMinor: -1_000,
  adjustmentAmountMinor: 0,
  settlementAmountMinor: 9_000,
  expectedSettlementAmountMinor: 9_000,
  identityDifferenceMinor: 0,
  identityStatus: 'matched',
  occurredAt: '2026-08-20T00:00:00Z',
  platformUpdatedAt: null,
  syncedAt: '2026-08-21T00:00:00Z',
  dataCompleteness: 'final',
  components: [],
} as const

describe('Finance detail pages', () => {
  beforeEach(() => {
    mocks.shops.mockReturnValue({
      data: [{ id: 'shop-1', shopName: 'Akeleo Fun Toys', timezone: 'America/Los_Angeles' }],
      isLoading: false,
      isError: false,
    })
    mocks.transactions.mockReturnValue({
      data: { items: [transaction], total: 1, page: 1, pageSize: 20 },
      isLoading: false,
      isError: false,
    })
    mocks.statement.mockReturnValue({
      data: {
        id: 'statement-1',
        platformStatementId: 'platform-statement-1',
        status: 'available',
        paymentStatus: 'paid',
        currency: 'USD',
        revenueAmountMinor: 10_000,
        feeAmountMinor: -1_000,
        adjustmentAmountMinor: 0,
        settlementAmountMinor: 9_000,
        expectedSettlementAmountMinor: 9_000,
        identityDifferenceMinor: 0,
        statementTransactionDifferenceMinor: 0,
        paymentStatementDifferenceMinor: 0,
        recexample81340158: 'matched',
        statementStartAt: '2026-08-14T00:00:00Z',
        statementEndAt: '2026-08-20T00:00:00Z',
        platformCreatedAt: '2026-08-20T00:00:00Z',
        syncedAt: '2026-08-21T00:00:00Z',
        transactions: [transaction],
        payments: [],
      },
      isLoading: false,
      isError: false,
    })
  })

  it('renders statement reconciliation and reuses the existing order detail route', () => {
    render(
      <MemoryRouter initialEntries={['/finance/statements/statement-1']}>
        <Routes>
          <Route path="/finance/statements/:statementId" element={<FinanceStatementDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '结算单详情' })).toBeInTheDocument()
    expect(screen.getByText('结算单、流水和付款已匹配')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'ERP-ORDER-1' })[0]).toHaveAttribute('href', '/orders/order-1')
  })

  it('requests the transaction list with server pagination and shop scope', () => {
    render(
      <MemoryRouter initialEntries={['/finance/transactions']}>
        <FinanceTransactionsPage />
      </MemoryRouter>,
    )

    expect(mocks.transactions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20, shopId: 'shop-1', currency: 'USD' }),
      true,
    )
    expect(screen.getByRole('heading', { name: '财务流水' })).toBeInTheDocument()
  })

  it('lists each order transaction with its payment state', () => {
    render(
      <MemoryRouter initialEntries={['/finance/orders']}>
        <FinanceOrdersPage />
      </MemoryRouter>,
    )

    expect(mocks.transactions).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, pageSize: 20, shopId: 'shop-1', currency: 'USD', type: 'ORDER' }),
      true,
    )
    expect(screen.getByRole('heading', { name: '订单财务' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'ERP-ORDER-1' })).toHaveAttribute('href', '/orders/order-1')
    expect(screen.getByText('已经完结')).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '对应结算单' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '流水号' })).not.toBeInTheDocument()
  })
})
