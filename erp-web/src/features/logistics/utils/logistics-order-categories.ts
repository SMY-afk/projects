export type LogisticsOrderCategory =
  'pending_shipment' | 'pending_collection' | 'partial_shipping' | 'in_transit' | 'delivered'

export const orderCategories: { key: LogisticsOrderCategory; label: string; elapsed: string }[] = [
  { key: 'pending_shipment', label: '待发货', elapsed: '未发货时长' },
  { key: 'pending_collection', label: '待揽收', elapsed: '未真实发货时长' },
  { key: 'partial_shipping', label: '部分发货', elapsed: '特殊情况' },
  { key: 'in_transit', label: '运输中', elapsed: '运输时长（从下单起）' },
  { key: 'delivered', label: '已送达', elapsed: '送达时长（已固定）' },
]

export function elapsedSince(createdAt: string, now: number): string {
  const elapsed = now - Date.parse(createdAt)
  if (!Number.isFinite(elapsed) || elapsed < 0) return '订单时间异常'
  const minutes = Math.floor(elapsed / 60_000)
  return `${Math.floor(minutes / 1440)}天 ${Math.floor((minutes % 1440) / 60)}小时 ${minutes % 60}分钟`
}

export function orderElapsed(
  order: { orderCreatedAt: string; platformStatus: string; deliveredAt?: string | null },
  now: number,
): string {
  if (['DELIVERED', 'COMPLETED'].includes(order.platformStatus)) {
    return order.deliveredAt ? elapsedSince(order.orderCreatedAt, Date.parse(order.deliveredAt)) : '送达时间待查询'
  }
  return elapsedSince(order.orderCreatedAt, now)
}
