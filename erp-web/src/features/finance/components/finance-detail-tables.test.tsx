import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { FinancePaymentTable } from './finance-payment-table'
import { FinanceOrderTable } from './finance-order-table'
import { FinanceStatementTable } from './finance-statement-table'
import { FinanceTransactionTable } from './finance-transaction-table'
import type { FinancePayment, FinanceStatement, FinanceTransaction } from '../types/finance.types'

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
} as FinanceTransaction

const statement = {
  id: 'statement-1',
  platformStatementId: 'platform-statement-1',
  status: 'available',
  currency: 'USD',
  settlementAmountMinor: 9_000,
  paymentStatus: 'paid',
  recexample81340158: 'matched',
  statementStartAt: '2026-08-14T00:00:00Z',
  statementEndAt: '2026-08-20T00:00:00Z',
  statementTransactionDifferenceMinor: 0,
  paymentStatementDifferenceMinor: 0,
} as FinanceStatement

const payment = {
  id: 'payment-1',
  platformPaymentId: 'platform-payment-1',
  status: 'paid',
  currency: 'USD',
  paymentAmountMinor: 9_000,
  statementAmountMinor: 9_000,
  differenceMinor: 0,
  recexample81340158: 'matched',
  bankReferenceMasked: '****1234',
  initiatedAt: '2026-08-20T00:00:00Z',
  paidAt: '2026-08-21T00:00:00Z',
} as FinancePayment

describe('Finance detail tables', () => {
  it('links statements to Finance detail and orders to the existing order detail route', () => {
    render(
      <MemoryRouter>
        <FinanceStatementTable statements={[statement]} loading={false} />
        <FinanceTransactionTable transactions={[transaction]} loading={false} />
      </MemoryRouter>,
    )

    expect(screen.getAllByRole('link', { name: 'platform-statement-1' })[0]).toHaveAttribute(
      'href',
      '/finance/statements/statement-1',
    )
    expect(screen.getAllByRole('link', { name: 'ERP-ORDER-1' })[0]).toHaveAttribute('href', '/orders/order-1')
    expect(screen.getByText('可用')).toBeInTheDocument()
    expect(screen.queryByText('available')).not.toBeInTheDocument()
  })

  it('shows only the masked bank reference in the payment table', () => {
    render(<FinancePaymentTable payments={[payment]} loading={false} />)

    expect(screen.getByText('****1234')).toBeInTheDocument()
    expect(screen.queryByText('12345678901234')).not.toBeInTheDocument()
  })

  it('shows the three order payment states and sends the selected state to server filtering', async () => {
    const user = userEvent.setup()
    const onPaymentStateChange = vi.fn()
    render(
      <MemoryRouter>
        <FinanceOrderTable
          transactions={[
            transaction,
            { ...transaction, id: 'transaction-refund', refundAmountMinor: -1_000 },
            { ...transaction, id: 'transaction-pending', basis: 'estimated', status: 'UNSETTLED' },
          ]}
          loading={false}
          onPaymentStateChange={onPaymentStateChange}
        />
      </MemoryRouter>,
    )

    const statusHeader = screen.getByRole('columnheader', { name: /^状态/ })
    expect(statusHeader).toBeInTheDocument()
    expect(statusHeader.querySelector('.ant-table-filter-trigger')).not.toBeNull()
    expect(screen.getByText('已经完结')).toBeInTheDocument()
    expect(screen.getByText('已付款后退款')).toBeInTheDocument()
    expect(screen.getByText('待付款')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '金额类型' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '口径' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '对应结算单' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '流水号' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'filter' }))
    const dropdown = document.querySelector('.ant-table-filter-dropdown')
    expect(dropdown).not.toBeNull()
    await user.click(within(dropdown as HTMLElement).getByText('已付款后退款'))
    await user.click(within(dropdown as HTMLElement).getByRole('button', { name: 'OK' }))

    expect(onPaymentStateChange).toHaveBeenCalledWith('refunded')
  })
})
