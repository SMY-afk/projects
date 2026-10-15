import { render, screen, within } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { OrderSummary } from '../types/order.types'
import { OrderList } from './order-list'

vi.mock('@/shared/components/erp-list/erp-list-page', () => ({
  ErpListPage: ({ columns, data }: { columns: Array<Record<string, unknown>>; data: OrderSummary[] }) => (
    <div>
      {columns
        .filter(
          (column) =>
            column.key === 'transactionChain' ||
            (typeof column.title === 'string' &&
              ['商家达人账号', '成交链路', '金额', '结算金额'].includes(column.title)),
        )
        .map((column) => {
          const label = column.key === 'transactionChain' ? '成交链路' : (column.title as string)
          const renderCell = column.render as
            ((value: unknown, order: OrderSummary, index: number) => React.ReactNode) | undefined
          return (
            <section data-testid={`column-${label}`} key={label}>
              <h2>{label}</h2>
              {column.key === 'transactionChain' ? (column.title as React.ReactNode) : null}
              {renderCell?.(undefined, data[0], 0)}
            </section>
          )
        })}
    </div>
  ),
}))

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})

describe('OrderList attribution layout', () => {
  it('renders the final settlement amount from the order list API', () => {
    renderOrder({ ...merchantCreatorOrder, settlementAmountMinor: 9_000 })

    expect(within(screen.getByTestId('column-结算金额')).getByText('US$90.00')).toBeInTheDocument()
  })

  it('renders the transaction-chain filter in the column header', () => {
    render(
      <OrderList
        data={[merchantCreatorOrder]}
        pagination={{ current: 1, pageSize: 20, total: 1 }}
        selectedOrderTypePath={['sample']}
        shopOptions={[]}
        onPageChange={vi.fn()}
        onSearchChange={vi.fn()}
        onStatusChange={vi.fn()}
        onShopChange={vi.fn()}
        onOpenDetail={vi.fn()}
        onAttributionChange={vi.fn()}
        onOrderTypeChange={vi.fn()}
        onContentFormChange={vi.fn()}
      />,
    )

    const chainColumn = screen.getByTestId('column-成交链路')
    expect(within(chainColumn).getByLabelText('成交链路筛选')).toBeInTheDocument()
    expect(within(chainColumn).getByText('样品订单（金额为0）')).toBeInTheDocument()
  })

  it('puts the merchant creator account inside the transaction-chain column', () => {
    render(
      <OrderList
        data={[merchantCreatorOrder]}
        pagination={{ current: 1, pageSize: 20, total: 1 }}
        shopOptions={[]}
        onPageChange={vi.fn()}
        onSearchChange={vi.fn()}
        onStatusChange={vi.fn()}
        onShopChange={vi.fn()}
        onOpenDetail={vi.fn()}
        onAttributionChange={vi.fn()}
        onOrderTypeChange={vi.fn()}
        onContentFormChange={vi.fn()}
      />,
    )

    expect(screen.queryByRole('heading', { name: '商家达人账号' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('heading', { name: '成交链路' })).toHaveLength(1)
    const chainColumn = screen.getByTestId('column-成交链路')
    expect(within(chainColumn).getByText('pinky66_shop')).toBeInTheDocument()
    expect(within(chainColumn).getByText('9443421243333405023')).toBeInTheDocument()
    expect(within(chainColumn).getByText('merchant_video_order')).toBeInTheDocument()
  })

  const attributionCopyCases: Array<{
    name: string
    createOrder: () => OrderSummary
    expected: string
  }> = [
    {
      name: 'confirmed self-operated order',
      createOrder: () => merchantCreatorOrder,
      expected: 'merchant_video_order',
    },
    {
      name: 'unknown attribution order',
      createOrder: () => createUnknownOrder(),
      expected: '未识别：订单详情未返回来源字段',
    },
    {
      name: 'affiliate-linked order',
      createOrder: () => createAffiliateOrder(),
      expected: '联盟达人订单（入口待识别）',
    },
    {
      name: 'self-operated sample order',
      createOrder: () => ({ ...merchantCreatorOrder, totalAmountMinor: 0 }),
      expected: '自家样品订单',
    },
    {
      name: 'affiliate sample order',
      createOrder: () => createAffiliateOrder(0),
      expected: '联盟样品订单',
    },
    {
      name: 'sample order without attribution evidence',
      createOrder: () => ({ ...createUnknownOrder(), totalAmountMinor: 0 }),
      expected: '样品订单·来源待识别',
    },
  ]

  it.each(attributionCopyCases)('renders fixed attribution copy for $name', ({ createOrder, expected }) => {
    renderOrder(createOrder())

    const chainColumn = screen.getByTestId('column-成交链路')
    expect(within(chainColumn).getByText(expected)).toBeInTheDocument()
  })
})

function renderOrder(order: OrderSummary) {
  render(
    <OrderList
      data={[order]}
      pagination={{ current: 1, pageSize: 20, total: 1 }}
      shopOptions={[]}
      onPageChange={vi.fn()}
      onSearchChange={vi.fn()}
      onStatusChange={vi.fn()}
      onShopChange={vi.fn()}
      onOpenDetail={vi.fn()}
      onAttributionChange={vi.fn()}
      onOrderTypeChange={vi.fn()}
      onContentFormChange={vi.fn()}
    />,
  )
}

function createUnknownOrder(): OrderSummary {
  return {
    ...merchantCreatorOrder,
    attribution: {
      ...merchantCreatorOrder.attribution,
      operatorSubject: 'unknown',
      chainCode: 'unknown',
      classificationStatus: 'unknown',
      creatorExternalId: null,
      creatorHandle: null,
      creatorAlias: null,
    },
  }
}

function createAffiliateOrder(totalAmountMinor = merchantCreatorOrder.totalAmountMinor): OrderSummary {
  return {
    ...merchantCreatorOrder,
    totalAmountMinor,
    attribution: {
      ...merchantCreatorOrder.attribution,
      operatorSubject: 'creator',
      chainCode: 'unknown',
      classificationStatus: 'derived',
      creatorExternalId: 'creator-1',
      creatorHandle: 'Creator One',
      creatorAlias: null,
    },
    affiliateItems: [
      {
        mainOrderId: merchantCreatorOrder.platformOrderId,
        creatorId: 'creator-1',
        creatorNickname: 'Creator One',
        productId: 'product-1',
        skuId: 'sku-1',
        orderCreatedAt: merchantCreatorOrder.placedAt,
      },
    ],
  }
}

const merchantCreatorOrder: OrderSummary = {
  id: 'order-1',
  shopId: 'shop-1',
  shopName: 'Akeleo Fun Toys',
  platformOrderId: 'platform-order-1',
  orderNumber: '946442003607933088',
  status: 'awaiting_shipment',
  externalStatus: 'AWAITING_SHIPMENT',
  fulfillmentStatus: 'unfulfilled',
  currency: 'USD',
  subtotalAmountMinor: 10367,
  shippingFeeMinor: 0,
  discountAmountMinor: 0,
  taxAmountMinor: 0,
  totalAmountMinor: 10367,
  buyerUsernameMasked: '-',
  itemSummary: '2.4G Remote Control Excavator',
  itemCount: 1,
  placedAt: '2026-08-19T08:00:00Z',
  platformUpdatedAt: '2026-08-19T08:00:00Z',
  syncedAt: '2026-08-19T08:01:00Z',
  attribution: {
    trafficSource: 'video',
    operatorSubject: 'self_operated',
    entryPoint: 'video',
    specialOrderType: 'standard',
    chainCode: 'merchant_video_order',
    classificationStatus: 'confirmed',
    creatorExternalId: '9443421243333405023',
    creatorHandle: 'pinky66_shop',
    creatorAlias: 'pinky66_shop',
  },
  affiliateItems: [],
}
