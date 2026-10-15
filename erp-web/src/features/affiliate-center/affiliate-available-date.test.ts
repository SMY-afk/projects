import { describe, expect, it } from 'vitest'
import { currentTikTokAffiliateDate, resolveAffiliateLatestAvailableDay } from './affiliate-available-date'

describe('currentTikTokAffiliateDate', () => {
  it('returns the current TikTok calendar date without a fixed delay', () => {
    const now = new Date('2026-08-27T02:00:00Z')

    expect(currentTikTokAffiliateDate('America/Los_Angeles', now)).toBe('2026-08-26')
    expect(currentTikTokAffiliateDate('Asia/Shanghai', now)).toBe('2026-08-27')
  })

  it('uses TikTok Affiliate fixed GMT-8 instead of Los Angeles daylight time', () => {
    const now = new Date('2026-08-28T07:30:00Z')

    expect(currentTikTokAffiliateDate('America/Los_Angeles', now)).toBe('2026-08-27')
  })

  it('falls back to UTC for a missing or invalid shop timezone', () => {
    const now = new Date('2026-08-27T02:00:00Z')

    expect(currentTikTokAffiliateDate(null, now)).toBe('2026-08-27')
    expect(currentTikTokAffiliateDate('invalid-timezone', now)).toBe('2026-08-27')
  })

  it('does not replace a missing TikTok observation with the system date', () => {
    expect(resolveAffiliateLatestAvailableDay(undefined)).toBeUndefined()
    expect(resolveAffiliateLatestAvailableDay('2026-09-02')).toBe('2026-09-02')
  })
})
