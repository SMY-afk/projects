export type OrderStatus =
  | 'unpaid'
  | 'on_hold'
  | 'awaiting_shipment'
  | 'awaiting_collection'
  | 'partially_shipped'
  | 'in_transit'
  | 'delivered'
  | 'completed'
  | 'cancelled'
  | 'unknown'

export type AffiliateContentForm =
  'video' | 'live' | 'product_showcase' | 'affiliate_product_page' | 'external_traffic_plan'

export interface OrderListParams {
  page: number
  pageSize: number
  shopId?: string
  keyword?: string
  status?: OrderStatus
  updatedFrom?: string
  updatedTo?: string
  trafficSource?: string
  operatorSubject?: string
  entryPoint?: string
  specialOrderType?: string
  classificationStatus?: string
  contentForm?: AffiliateContentForm
}

export type OrderAttributionFilterKey =
  'trafficSource' | 'operatorSubject' | 'entryPoint' | 'specialOrderType' | 'classificationStatus'

export interface AffiliateOrderItem {
  mainOrderId: string
  creatorId?: string | null
  creatorNickname?: string | null
  campaignId?: string | null
  productId: string
  productName?: string | null
  skuId: string
  skuName?: string | null
  orderCreatedAt: string
  promotionId?: string | null
  promotionType?: number | null
  contentForm?: string | null
  contentFormLabel?: string | null
  commissionBase?: string | number | null
  commissionCurrency?: string | null
  commissionRate?: string | number | null
  estimatedStandardCommission?: string | number | null
}

export interface OrderSummary {
  id: string
  shopId: string
  shopName: string
  platformOrderId: string
  orderNumber: string
  status: OrderStatus
  externalStatus: string
  fulfillmentStatus: string
  currency: string
  subtotalAmountMinor: number
  shippingFeeMinor: number
  discountAmountMinor: number
  taxAmountMinor: number
  totalAmountMinor: number
  settlementAmountMinor?: number | null
  buyerUsernameMasked?: string | null
  itemSummary: string
  itemCount: number
  placedAt: string
  paidAt?: string | null
  platformUpdatedAt: string
  syncedAt: string
  attribution: OrderAttributionSummary
  affiliateItems: AffiliateOrderItem[]
}

export interface OrderLine {
  id: string
  platformLineId: string
  platformProductId?: string | null
  platformSkuId?: string | null
  sellerSku?: string | null
  productName: string
  skuName?: string | null
  imageUrl?: string | null
  quantity: number
  originalUnitPriceMinor: number
  saleUnitPriceMinor: number
  discountAmountMinor: number
  lineTotalAmountMinor: number
}

export interface OrderFulfillment {
  id: string
  platformPackageId: string
  status: string
  carrier?: string | null
  trackingNumberMasked?: string | null
  shippedAt?: string | null
  deliveredAt?: string | null
}

export interface MaskedOrderRecipient {
  name?: string | null
  phone?: string | null
  address?: string | null
  countryCode?: string | null
  purged: boolean
}

export interface OrderAttributionEvidence {
  source: string
  fieldPath: string
  value: string
  strength: string
  reason: string
  reasonLabel: string
}

export interface OrderAttributionSummary {
  trafficSource: string
  operatorSubject: string
  entryPoint: string
  specialOrderType: string
  chainCode: string
  classificationStatus: string
  creatorExternalId?: string | null
  creatorHandle?: string | null
  creatorAlias?: string | null
}

export interface OrderAttribution extends OrderAttributionSummary {
  classificationMethod: string
  sourceUpdatedAt?: string | null
  evidenceSummary: OrderAttributionEvidence[]
}

export interface OrderDetail extends OrderSummary {
  lines: OrderLine[]
  fulfillments: OrderFulfillment[]
  maskedRecipient?: MaskedOrderRecipient | null
  attribution: OrderAttribution
}

export interface OrderRecipient {
  name?: string | null
  phone?: string | null
  address?: string | null
  countryCode?: string | null
  purged: boolean
}

export interface OrderListResult {
  items: OrderSummary[]
  total: number
  page: number
  pageSize: number
}

export interface OrderShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
}
