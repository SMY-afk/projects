import { describe, expect, it } from 'vitest'
import { financeCurrencyDigits, formatFinanceMoney, formatFinanceTime } from './finance-format'

describe('Finance formatting', () => {
  it('formats zero, two and three decimal currencies from minor units', () => {
    expect(financeCurrencyDigits('JPY')).toBe(0)
    expect(financeCurrencyDigits('USD')).toBe(2)
    expect(financeCurrencyDigits('KWD')).toBe(3)
    expect(formatFinanceMoney(1234, 'JPY')).toContain('1,234')
    expect(formatFinanceMoney(1234, 'USD')).toContain('12.34')
    expect(formatFinanceMoney(1234, 'KWD')).toContain('1.234')
  })

  it('formats timestamps in the selected shop timezone', () => {
    expect(formatFinanceTime('2026-08-21T00:00:00Z', 'America/Los_Angeles')).toContain('2026-08-20')
    expect(formatFinanceTime(null, 'UTC')).toBe('--')
  })
})
