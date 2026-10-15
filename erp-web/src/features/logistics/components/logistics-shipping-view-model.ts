import type { LogisticsPackage, LogisticsShippingQuote, LogisticsTaskItem } from '../types/logistics.types'

export const shippingQuoteKey = (quote: LogisticsShippingQuote) =>
  `${quote.carrierId}:${quote.serviceId}:${quote.accountId ?? ''}`

export function formatShippingFee(quote: LogisticsShippingQuote) {
  if (quote.amountMinor === null || !quote.currency) return '人工询价'
  return `${quote.currency} ${(quote.amountMinor / 100).toFixed(2)}`
}

export function formatDeliveryEstimate(quote: LogisticsShippingQuote) {
  if (quote.estimatedDaysMin === null) return '暂未提供'
  const maximum = quote.estimatedDaysMax ?? quote.estimatedDaysMin
  return quote.estimatedDaysMin === maximum ? `${maximum} 天` : `${quote.estimatedDaysMin}-${maximum} 天`
}

export function resolveDispatchLines(packageItem: LogisticsPackage, taskItems: LogisticsTaskItem[]) {
  const taskItemMap = new Map(taskItems.map((item) => [item.id, item]))
  return packageItem.items.map((item) => {
    const taskItem = taskItemMap.get(item.taskItemId)
    return {
      id: item.taskItemId,
      sku: taskItem?.sellerSku ?? taskItem?.platformSkuId ?? '-',
      productName: taskItem?.productName ?? '未知商品',
      specification: taskItem?.skuName ?? '-',
      quantity: item.quantity,
    }
  })
}
