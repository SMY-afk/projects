import { describe, expect, it } from 'vitest'
import { distributionTotal, formatPercentChange } from './dashboard-format'

describe('dashboard formatting', () => {
  it('formats comparable percentages without inventing a zero baseline', () => {
    expect(formatPercentChange(120, 100)).toBe('+20.00%')
    expect(formatPercentChange(1, 0)).toBe('—')
  })

  it('totals the selected distribution metric', () => {
    const rows = [
      { key: 'a', orderCount: 1, salesVolume: 2, salesAmountMinor: 300 },
      { key: 'b', orderCount: 4, salesVolume: 5, salesAmountMinor: 600 },
    ]
    expect(distributionTotal(rows, 'salesVolume')).toBe(7)
    expect(distributionTotal(rows, 'salesAmountMinor')).toBe(900)
  })
})
