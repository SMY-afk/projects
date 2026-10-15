import type { DashboardTrendPoint } from '../types/dashboard.types'

export type MetricTone = 'positive' | 'negative' | 'neutral'

export function metricChange(current?: number, previous?: number) {
  if (current === undefined || previous === undefined) return undefined
  if (previous === 0) return current === 0 ? 0 : undefined
  return ((current - previous) / Math.abs(previous)) * 100
}

export function metricTone(change: number | undefined, positiveWhenUp = true): MetricTone {
  if (change === undefined || change === 0) return 'neutral'
  return (positiveWhenUp ? change > 0 : change < 0) ? 'positive' : 'negative'
}

export function trendValues(
  points: DashboardTrendPoint[],
  field: keyof Pick<DashboardTrendPoint, 'salesAmountMinor' | 'netSalesAmountMinor' | 'orderCount' | 'salesVolume'>,
) {
  return points.map((point) => point[field])
}
