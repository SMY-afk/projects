import { isFeatureMockEnabled } from '@/services/api-mode'
import { request } from '@/services/http-client'
import type {
  OrderAttribution,
  OrderAttributionSummary,
  OrderDetail,
  OrderListParams,
  OrderListResult,
  OrderRecipient,
  OrderShopOption,
  OrderSummary,
} from '../types/order.types'

const now = '2026-08-12T08:00:00Z'
const orders: OrderSummary[] = [
  {
    id: 'e4408786-af60-545e-8f8c-5ef22a71e675',
    shopId: 'mock-shop',
    shopName: 'Akeleo Fun Toys',
    platformOrderId: 'TT-89420',
    orderNumber: 'TT-US-89420',
    status: 'awaiting_shipment',
    externalStatus: 'AWAITING_SHIPMENT',
    fulfillmentStatus: 'unfulfilled',
    currency: 'USD',
    subtotalAmountMinor: 29900,
    shippingFeeMinor: 0,
    discountAmountMinor: 0,
    taxAmountMinor: 0,
    totalAmountMinor: 29900,
    settlementAmountMinor: null,
    buyerUsernameMasked: 'J***',
    itemSummary: '蓝色童车 等 1 件',
    itemCount: 1,
    placedAt: now,
    paidAt: now,
    platformUpdatedAt: now,
    syncedAt: now,
    attribution: {
      trafficSource: 'unknown',
      operatorSubject: 'unknown',
      entryPoint: 'unknown',
      specialOrderType: 'unknown',
      chainCode: 'unknown',
      classificationStatus: 'unknown',
    },
    affiliateItems: [],
  },
]

const detailFor = (order: OrderSummary): OrderDetail => ({
  ...order,
  lines: [
    {
      id: 'line-1',
      platformLineId: 'line-1',
      platformProductId: 'product-1',
      platformSkuId: 'sku-1',
      sellerSku: 'A-AHKLD-BLUE',
      productName: '蓝色童车',
      skuName: '蓝色',
      quantity: 1,
      originalUnitPriceMinor: 29900,
      saleUnitPriceMinor: 29900,
      discountAmountMinor: 0,
      lineTotalAmountMinor: 29900,
    },
  ],
  fulfillments: [],
  maskedRecipient: { name: 'J***', phone: '******7890', address: 'US Seattle ***', countryCode: 'US', purged: false },
  attribution: {
    trafficSource: 'unknown',
    operatorSubject: 'unknown',
    entryPoint: 'unknown',
    specialOrderType: 'unknown',
    chainCode: 'unknown',
    classificationStatus: 'unknown',
    classificationMethod: 'shop_order_detail',
    sourceUpdatedAt: now,
    evidenceSummary: [
      {
        source: 'external_order_evidence',
        fieldPath: 'affiliate_order|ads_order',
        value: 'missing_order_level_key',
        strength: 'unsupported',
        reason: 'platform_no_order_level_evidence',
        reasonLabel: '平台无订单级证据',
      },
    ],
  },
})

const unknownAttributionSummary = (): OrderAttributionSummary => ({
  trafficSource: 'unknown',
  operatorSubject: 'unknown',
  entryPoint: 'unknown',
  specialOrderType: 'unknown',
  chainCode: 'unknown',
  classificationStatus: 'unknown',
})

const unknownAttributionDetail = (): OrderAttribution => ({
  ...unknownAttributionSummary(),
  classificationMethod: 'shop_order_detail',
  sourceUpdatedAt: null,
  evidenceSummary: [],
})

export const normalizeOrderListResult = (result: OrderListResult): OrderListResult => ({
  ...result,
  items: result.items.map((item) => ({
    ...item,
    attribution: item.attribution ?? unknownAttributionSummary(),
    affiliateItems: item.affiliateItems ?? [],
  })),
})

export const normalizeOrderDetail = (detail: OrderDetail): OrderDetail => ({
  ...detail,
  attribution: detail.attribution ?? unknownAttributionDetail(),
  affiliateItems: detail.affiliateItems ?? [],
})

const mockOrderApi = {
  getList: (params: OrderListParams, signal?: AbortSignal): Promise<OrderListResult> => {
    void signal
    const keyword = params.keyword?.trim().toLowerCase()
    const filtered = orders.filter(
      (order) =>
        (!params.shopId || order.shopId === params.shopId) &&
        (!params.status || order.status === params.status) &&
        (!params.trafficSource || order.attribution.trafficSource === params.trafficSource) &&
        (!params.operatorSubject || order.attribution.operatorSubject === params.operatorSubject) &&
        (!params.entryPoint || order.attribution.entryPoint === params.entryPoint) &&
        (!params.specialOrderType ||
          (params.specialOrderType === 'sample'
            ? order.totalAmountMinor === 0
            : order.attribution.specialOrderType === params.specialOrderType)) &&
        (!params.classificationStatus || order.attribution.classificationStatus === params.classificationStatus) &&
        (!params.contentForm || order.affiliateItems.some((item) => item.contentForm === params.contentForm)) &&
        (!keyword ||
          [order.orderNumber, order.platformOrderId, order.itemSummary].some((value) =>
            value.toLowerCase().includes(keyword),
          )),
    )
    const start = (params.page - 1) * params.pageSize
    return Promise.resolve({
      items: filtered.slice(start, start + params.pageSize),
      total: filtered.length,
      page: params.page,
      pageSize: params.pageSize,
    })
  },
  getDetail: (orderId: string): Promise<OrderDetail> =>
    Promise.resolve(detailFor(orders.find((item) => item.id === orderId) ?? orders[0])),
  getRecipient: (): Promise<OrderRecipient> =>
    Promise.resolve({
      name: 'James',
      phone: '1234567890',
      address: 'Seattle, WA, US',
      countryCode: 'US',
      purged: false,
    }),
  listShops: (): Promise<OrderShopOption[]> =>
    Promise.resolve([
      {
        id: 'mock-shop',
        shopName: 'Akeleo Fun Toys',
        platform: 'tiktok',
        platformShopId: 'mock-tiktok-shop',
      },
    ]),
}

const httpOrderApi = {
  getList: async (params: OrderListParams, signal?: AbortSignal) =>
    normalizeOrderListResult(await request<OrderListResult>({ method: 'get', url: '/orders', params, signal })),
  getDetail: async (orderId: string) =>
    normalizeOrderDetail(await request<OrderDetail>({ method: 'get', url: `/orders/${orderId}` })),
  getRecipient: (orderId: string) => request<OrderRecipient>({ method: 'get', url: `/orders/${orderId}/recipient` }),
  listShops: () => request<OrderShopOption[]>({ method: 'get', url: '/shops' }),
}

export const orderApi = isFeatureMockEnabled('orders') ? mockOrderApi : httpOrderApi
