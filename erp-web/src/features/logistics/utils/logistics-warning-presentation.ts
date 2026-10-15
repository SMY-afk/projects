import type { LogisticsOrderAlert } from '../types/logistics-status.types'

export const warningLabels: Record<LogisticsOrderAlert, string> = {
  unshipped_48h: '未发货预警（48小时）',
  uncollected_48h: '未真实发货预警（48小时）',
  undelivered_77h: '未送达预警（77小时）',
}

export function overdueDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60)
  return minutes ? `${Math.floor(minutes / 1440)}天 ${Math.floor((minutes % 1440) / 60)}小时 ${minutes % 60}分钟` : '不足1分钟'
}
