import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { isFinanceDateDisabled, resolveFinanceRange } from './finance-range'

describe('Finance date range', () => {
  it('converts shop-local inclusive dates to a UTC half-open window', () => {
    const result = resolveFinanceRange([dayjs('2026-08-01'), dayjs('2026-08-20')], 'America/Los_Angeles')

    expect(result).toEqual({
      from: '2026-08-01T07:00:00.000Z',
      to: '2026-08-21T07:00:00.000Z',
    })
  })

  it('disables future dates and dates more than 29 days from the range start', () => {
    const from = dayjs('2026-08-01')
    const maxDate = dayjs('2026-08-21')

    expect(isFinanceDateDisabled(dayjs('2026-08-22'), from, maxDate)).toBe(true)
    expect(isFinanceDateDisabled(dayjs('2026-08-21'), from, maxDate)).toBe(false)
    expect(isFinanceDateDisabled(dayjs('2026-09-01'), from, dayjs('2026-09-30'))).toBe(true)
  })
})
