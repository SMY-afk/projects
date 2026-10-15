import { describe, expect, it } from 'vitest'
import { latestCompletedShopDate } from './shop-date'

describe('latestCompletedShopDate', () => {
  it('uses the shop calendar rather than the browser calendar', () => {
    const now = new Date('2026-08-21T02:45:00Z')

    expect(latestCompletedShopDate('America/Los_Angeles', now)).toBe('2026-08-19')
    expect(latestCompletedShopDate('Asia/Shanghai', now)).toBe('2026-08-20')
  })

  it('falls back to UTC when the shop timezone is missing or invalid', () => {
    const now = new Date('2026-08-21T02:45:00Z')

    expect(latestCompletedShopDate(null, now)).toBe('2026-08-20')
    expect(latestCompletedShopDate('not-a-timezone', now)).toBe('2026-08-20')
  })
})
