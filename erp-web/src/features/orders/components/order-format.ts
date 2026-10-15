import type { AffiliateOrderItem, OrderAttributionSummary, OrderSummary } from '../types/order.types'

export const UNKNOWN_ATTRIBUTION_LABEL = '未识别：订单详情未返回来源字段'
export const AFFILIATE_LINKED_LABEL = '联盟达人订单（入口待识别）'
export const AFFILIATE_EVIDENCE_LABEL = '联盟证据已关联'

export const formatMoney = (amountMinor: number, currency: string) =>
  new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(amountMinor / 100)

const fulfillmentStatusLabels: Record<string, string> = {
  unfulfilled: '未履约',
  pending: '待处理',
  ready_to_ship: '待发货',
  awaiting_shipment: '待发货',
  awaiting_collection: '待揽收',
  partially_shipped: '部分发货',
  shipped: '已发货',
  in_transit: '运输中',
  out_for_delivery: '派送中',
  delivered: '已送达',
  completed: '已完成',
  cancelled: '已取消',
  failed: '配送失败',
  exception: '物流异常',
  returned: '已退回',
  unknown: '未知',
}

export const formatFulfillmentStatus = (status?: string | null) => {
  if (!status?.trim()) return '未知'
  const normalized = status
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')
  return fulfillmentStatusLabels[normalized] ?? '未知'
}

export const formatAttributionDimension = (value?: string | null) =>
  value === 'unknown' || !value?.trim() ? UNKNOWN_ATTRIBUTION_LABEL : value

export const getSampleOrderLabel = (
  order: Pick<OrderSummary, 'totalAmountMinor' | 'attribution' | 'affiliateItems'>,
) => {
  if (order.totalAmountMinor !== 0) return null
  if (order.affiliateItems.length || order.attribution.operatorSubject === 'creator') {
    return '联盟样品订单'
  }
  if (order.attribution.operatorSubject === 'self_operated') {
    return '自家样品订单'
  }
  return '样品订单·来源待识别'
}

export interface AffiliateOrderDisplay {
  chainLabel: string
  creatorLabel: string
  commissionLabel: string
  itemCount: number
}

const affiliateContentFormLabels: Record<string, string> = {
  product_showcase: '商品橱窗',
  video: '视频',
  live: '直播',
  affiliate_product_page: '联盟商品页',
  external_traffic_plan: '外部流量计划',
}

export const getAffiliateContentFormLabels = (items?: AffiliateOrderItem[]) => [
  ...new Set(
    (items ?? [])
      .map(
        (item) =>
          item.contentFormLabel?.trim() ||
          (item.contentForm ? affiliateContentFormLabels[item.contentForm] : undefined),
      )
      .filter((value): value is string => Boolean(value)),
  ),
]

export const getAffiliateVideoIds = (items?: AffiliateOrderItem[]) => [
  ...new Set(
    (items ?? [])
      .filter((item) => item.contentForm === 'video' || item.promotionType === 2)
      .map((item) => item.promotionId?.trim())
      .filter((value): value is string => Boolean(value)),
  ),
]

export interface OrderCreatorDisplay {
  creatorId?: string
  alias?: string
}

export const getOrderCreatorDisplay = (attribution?: OrderAttributionSummary | null): OrderCreatorDisplay | null => {
  if (attribution?.operatorSubject !== 'self_operated') return null
  const creatorId = attribution?.creatorExternalId?.trim()
  const alias = attribution?.creatorAlias?.trim()
  return creatorId || alias
    ? {
        ...(creatorId ? { creatorId } : {}),
        ...(alias ? { alias } : {}),
      }
    : null
}

export const formatAffiliateCommission = (items: AffiliateOrderItem[]) => {
  const amounts = items
    .map((item) => Number(item.estimatedStandardCommission))
    .filter((amount) => Number.isFinite(amount))
  if (!amounts.length) return '预计佣金待返回'
  const currency = items.find((item) => item.commissionCurrency)?.commissionCurrency
  const total = amounts.reduce((sum, amount) => sum + amount, 0)
  if (!currency) return `预计佣金 ${total.toFixed(2)}`
  return `预计佣金 ${new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(total)}`
}

export const getAffiliateOrderDisplay = (items?: AffiliateOrderItem[]): AffiliateOrderDisplay | null => {
  if (!items?.length) return null
  const creators = [
    ...new Set(
      items
        .map((item) => item.creatorNickname?.trim() || item.creatorId?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ]
  return {
    chainLabel: AFFILIATE_LINKED_LABEL,
    creatorLabel: creators.length ? creators.join('、') : '达人信息待返回',
    commissionLabel: formatAffiliateCommission(items),
    itemCount: items.length,
  }
}
