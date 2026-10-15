import { describe, expect, it } from 'vitest'
import { bestsellerQueryKeys } from './bestseller.queries'

describe('bestsellerQueryKeys', () => {
  it('contains every ranking query dimension', () => {
    const base = {
      shopId: 'shop-1',
      date: '2026-08-19',
      timeSlot: '7D' as const,
      currency: 'USD' as const,
      authorType: 'ALL' as const,
    }
    const key = bestsellerQueryKeys.list('creators', base)

    expect(key).toEqual(['bestsellers', 'list', 'shop-1', 'creators', '2026-08-19', '7D', 'USD', 'ALL'])
    expect(bestsellerQueryKeys.list('creators', { ...base, authorType: 'AFFILIATE' })).not.toEqual(key)
  })
})
