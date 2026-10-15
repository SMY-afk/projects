import type { DashboardDistributionItem, DistributionMetric } from '../types/dashboard.types'

export const formatNumber = (value: number) => new Intl.NumberFormat('en-US').format(value)

export const formatMoney = (minor: number, currency: string) => {
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(minor / 100)
  } catch {
    return `${currency} ${(minor / 100).toFixed(2)}`
  }
}

export const formatPercentChange = (current: number, comparison: number) => {
  if (comparison === 0) return current === 0 ? '0.00%' : '—'
  const percent = ((current - comparison) / comparison) * 100
  return `${percent >= 0 ? '+' : ''}${percent.toFixed(2)}%`
}

export const distributionValue = (item: DashboardDistributionItem, metric: DistributionMetric) => item[metric]

export const distributionTotal = (items: DashboardDistributionItem[], metric: DistributionMetric) =>
  items.reduce((total, item) => total + distributionValue(item, metric), 0)

export const platformLabel = (value: string) => (value.toLowerCase() === 'tiktok' ? 'TikTok' : value)

export const countryLabel = (code: string) => {
  if (code === 'UNKNOWN') return '未知国家/地区'
  try {
    return new Intl.DisplayNames(['zh-CN'], { type: 'region' }).of(code) ?? code
  } catch {
    return code
  }
}
