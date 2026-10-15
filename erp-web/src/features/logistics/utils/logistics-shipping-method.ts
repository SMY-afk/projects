export function shippingMethodLabel(value?: string | null, fulfillmentType?: string | null) {
  if (!value) return '暂未获取'
  if (value === 'SELLER') return fulfillmentType === 'FULFILLMENT_BY_TIKTOK' ? '物流方式待确认' : '商家物流'
  if (value === 'TIKTOK') {
    if (fulfillmentType === 'FULFILLMENT_BY_TIKTOK') return 'FBT物流'
    if (fulfillmentType === 'FULFILLMENT_BY_SELLER') return 'TikTok物流'
    return '平台物流（具体类型待确认）'
  }
  return value
}
