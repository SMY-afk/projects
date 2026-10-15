import { describe, expect, it } from 'vitest'
import { metricChange, metricTone, trendValues } from './dashboard-metric-utils'

describe('dashboard metric presentation', () => {
  it('calculates comparable changes without inventing a zero baseline', () => {
    expect(metricChange(120, 100)).toBe(20)
    expect(metricChange(0, 0)).toBe(0)
    expect(metricChange(1, 0)).toBeUndefined()
  })

  it('supports metrics where a lower value is better', () => {
    expect(metricTone(-10, false)).toBe('positive')
    expect(metricTone(10, false)).toBe('negative')
  })

  it('uses the real trend point values for sparklines', () => {
    const points = [
      { date: '2026-09-20', orderCount: 2, salesVolume: 3, salesAmountMinor: 400, netSalesAmountMinor: 350 },
      { date: '2026-09-21', orderCount: 4, salesVolume: 5, salesAmountMinor: 600, netSalesAmountMinor: 520 },
    ]
    expect(trendValues(points, 'salesAmountMinor')).toEqual([400, 600])
    expect(trendValues(points, 'orderCount')).toEqual([2, 4])
  })
})
