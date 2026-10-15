import type { AffiliateContentForm, OrderListParams } from '../types/order.types'

export const affiliateContentFormOptions: Array<{
  value: AffiliateContentForm
  label: string
}> = [
  { value: 'video', label: '视频' },
  { value: 'live', label: '直播' },
  { value: 'product_showcase', label: '商品橱窗' },
  { value: 'affiliate_product_page', label: '联盟商品页' },
  { value: 'external_traffic_plan', label: '外部流量计划' },
]

const affiliateChainContentOptions = affiliateContentFormOptions.map(({ value, label }) => ({
  value,
  label: label.endsWith('订单') ? label : `${label}订单`,
}))

export const orderTypeOptions = [
  {
    value: 'all',
    label: '全部成交链路',
  },
  {
    value: 'creator',
    label: '联盟达人订单',
    children: affiliateChainContentOptions,
  },
  { value: 'self_operated', label: '自家订单' },
  { value: 'unknown', label: '来源待识别' },
  { value: 'sample', label: '样品订单（金额为0）' },
  { value: 'purchase_sample_rebate', label: '买样返款订单' },
]

export const getOrderTypePath = (params: OrderListParams): string[] | undefined => {
  if (params.specialOrderType === 'sample' || params.specialOrderType === 'purchase_sample_rebate') {
    return [params.specialOrderType]
  }
  if (params.operatorSubject === 'creator') {
    return ['creator', ...(params.contentForm ? [params.contentForm] : [])]
  }
  if (params.operatorSubject === 'self_operated' || params.operatorSubject === 'unknown') {
    return [params.operatorSubject]
  }
  return undefined
}

type OrderTypeFilters = Partial<
  Pick<OrderListParams, 'trafficSource' | 'operatorSubject' | 'entryPoint' | 'specialOrderType' | 'contentForm'>
>

export const getOrderTypeFilters = (path?: string[]): OrderTypeFilters => {
  const [type, contentForm] = path ?? []
  if (type === 'creator') {
    return {
      operatorSubject: 'creator',
      ...(affiliateContentFormOptions.some((option) => option.value === contentForm)
        ? { contentForm: contentForm as AffiliateContentForm }
        : {}),
    }
  }
  if (type === 'self_operated' || type === 'unknown') {
    return { operatorSubject: type }
  }
  if (type === 'sample' || type === 'purchase_sample_rebate') {
    return { specialOrderType: type }
  }
  return {}
}
