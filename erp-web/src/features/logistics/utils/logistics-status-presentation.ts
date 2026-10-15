import type { LogisticsStatusOrder, LogisticsStatusPackage } from '../types/logistics-status.types'

export const trackingLabels: Record<string, string> = {
  pending_recheck: '等待后台重新核对',
  order_created: '订单已创建',
  ready_for_collection: '已打包待揽收',
  info_received: '已收到物流信息',
  picked_up: '已揽收',
  in_transit: '运输中',
  out_for_delivery: '派送中',
  delivered: '已送达',
  exception: '物流异常',
  returned: '已退回',
  cancelled: '已取消',
}
export const packageLabels: Record<string, string> = {
  AWAITING_SHIPMENT: '待发货',
  PARTIALLY_SHIPPING: '部分发货',
  AWAITING_COLLECTION: '待揽收',
  IN_TRANSIT: '运输中',
  DELIVERED: '已送达',
  COMPLETED: '已完成',
}
export const formatTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '-'
export const packageSummary = (packages: LogisticsStatusPackage[]) =>
  packages.length
    ? packages.map((item) => packageLabels[item.packageStatus] ?? item.packageStatus).join('、')
    : '暂无包裹'
export const cachedTracking = (order: LogisticsStatusOrder) => {
  if (order.officialCheckedAt) return trackingLabels[order.officialTrackingStatus ?? ''] ?? null
  const statuses = [...new Set(order.packages.map((item) => item.trackingStatus).filter(Boolean))]
  return statuses.length ? statuses.map((status) => trackingLabels[status ?? ''] ?? status).join('、') : null
}
