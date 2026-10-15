import dayjs from 'dayjs'
import { describe, expect, it, vi } from 'vitest'
import type { AffiliateVideoListQuery, AffiliateVideoPage } from '../types/affiliate-center.types'
import { findLatestCompleteVideoDay } from './use-latest-affiliate-video-day'

const emptyPage = (status?: string): AffiliateVideoPage => ({
  run: status
    ? {
        runId: 'run-1',
        status,
        fetchedCount: 1,
        persistedCount: 1,
        startedAt: '2026-08-27T00:00:00Z',
        finishedAt: '2026-08-27T00:01:00Z',
        freshAt: null,
        errorCategory: null,
        errorSummary: null,
      }
    : null,
  query: {
    shopId: 'shop-1',
    windowStart: '2026-08-17',
    windowEnd: '2026-08-23',
    shopTimezone: 'America/Los_Angeles',
    currency: 'USD',
    filters: {},
  },
  items: [],
  page: 1,
  pageSize: 1,
  total: status ? 1 : 0,
  summary: {
    videoCount: status ? 1 : 0,
    gmvMinor: 0,
    orderCount: 0,
    itemsSold: 0,
    views: 0,
    productImpressions: 0,
  },
  sort: 'gmvMinor',
  order: 'desc',
})

describe('findLatestCompleteVideoDay', () => {
  it('walks backward until it finds the latest complete TikTok snapshot', async () => {
    const loader = vi.fn((query: AffiliateVideoListQuery) =>
      Promise.resolve(emptyPage(query.to === '2026-08-23' ? 'succeeded' : undefined)),
    )

    const result = await findLatestCompleteVideoDay('shop-1', 'USD', dayjs('2026-08-25'), loader)

    expect(result).toBe('2026-08-23')
    expect(loader).toHaveBeenCalledTimes(3)
    expect(loader).toHaveBeenLastCalledWith(
      expect.objectContaining({ from: '2026-08-17', to: '2026-08-23', pageSize: 1 }),
    )
  })

  it('does not treat partial snapshots as available presets', async () => {
    const loader = vi.fn(() => Promise.resolve(emptyPage('partial')))

    const result = await findLatestCompleteVideoDay('shop-1', 'USD', dayjs('2026-08-25'), loader)

    expect(result).toBeUndefined()
  })
})
