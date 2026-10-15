import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VideoQuery } from '../types/data.types'
import { dataQueryKeys, useVideosQuery } from './data.queries'

const apiMocks = vi.hoisted(() => ({ videos: vi.fn(), resync: vi.fn() }))

vi.mock('../api/data.api', () => ({
  dataApi: {
    videos: apiMocks.videos,
    resync: apiMocks.resync,
  },
}))

describe('video queries', () => {
  beforeEach(() => {
    apiMocks.videos.mockReset()
    apiMocks.resync.mockReset()
  })

  it('keys the cache by every range and ranking dimension', () => {
    const query = {
      shopId: 'shop-1',
      from: '2026-08-01T00:00:00.000Z',
      to: '2026-08-16T00:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }
    const sort = { sortBy: 'gmv' as const, sortOrder: 'desc' as const }

    expect(dataQueryKeys.videos(query, sort)).toEqual([
      'data',
      'videos',
      'shop-1',
      query.from,
      query.to,
      'USD',
      'ALL',
      sort,
    ])
  })

  it('automatically queues the exact missing window and keeps the stale response for the syncing state', async () => {
    const query = {
      shopId: 'shop-1',
      from: '2026-08-01T00:00:00.000Z',
      to: '2026-08-16T00:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }
    apiMocks.videos.mockResolvedValue({
      apiVersion: 'v1',
      source: 'local_detail',
      range: {
        windowStart: query.from,
        windowEnd: query.to,
        shopTimezone: 'UTC',
        isPartial: false,
      },
      freshness: { isStale: true },
      errors: [{ code: 'data_unavailable', message: 'missing', action: 'resync' }],
      data: [],
    })
    apiMocks.resync.mockResolvedValue({ data: { jobIds: ['job-1'] } })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(() => useVideosQuery(query, { sortBy: 'gmv', sortOrder: 'desc' }), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    await waitFor(() =>
      expect(apiMocks.resync).toHaveBeenCalledWith({
        shopId: 'shop-1',
        resourceTypes: ['video'],
        windowStart: query.from,
        windowEnd: query.to,
        currency: 'USD',
        accountType: 'ALL',
      }),
    )
    expect(result.current.data?.freshness.isStale).toBe(true)
  })

  it('requests a new range and replaces ranking order and every returned metric together', async () => {
    const last30d = {
      shopId: 'shop-1',
      from: '2026-07-21T00:00:00.000Z',
      to: '2026-08-20T00:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }
    const today = { ...last30d, from: '2026-08-19T00:00:00.000Z' }
    const sort = { sortBy: 'gmv' as const, sortOrder: 'desc' as const }
    const monthFields = { views: 300, gmvAmount: '30.00', gpmAmount: '10.00', clickThroughRate: '0.30' }
    const todayFields = { views: 20, gmvAmount: '2.00', gpmAmount: '1.00', clickThroughRate: '0.10' }
    apiMocks.videos.mockImplementation((query: VideoQuery) =>
      Promise.resolve({
        apiVersion: 'v1',
        source: 'local_detail',
        range: {
          windowStart: query.from,
          windowEnd: query.to,
          shopTimezone: 'UTC',
          isPartial: false,
        },
        freshness: { isStale: false, asOf: '2026-08-19T07:30:00Z' },
        errors: [],
        data:
          query.from === today.from
            ? [video('video-today-first', todayFields), video('video-month-first', monthFields)]
            : [video('video-month-first', monthFields), video('video-today-first', todayFields)],
      }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result, rerender } = renderHook(({ query }) => useVideosQuery(query, sort), {
      initialProps: { query: last30d },
      wrapper,
    })
    await waitFor(() => expect(result.current.data?.data[0]?.platformExternalId).toBe('video-month-first'))
    expect(result.current.data?.data[0]?.fields).toEqual(monthFields)

    rerender({ query: today })

    await waitFor(() => expect(result.current.data?.data[0]?.platformExternalId).toBe('video-today-first'))
    expect(apiMocks.videos).toHaveBeenLastCalledWith(today, sort)
    expect(result.current.data?.data[0]?.fields).toEqual(todayFields)
  })

  it('refetches when returning to a previously viewed range despite the global fresh cache', async () => {
    const last30d = {
      shopId: 'shop-1',
      from: '2026-07-21T00:00:00.000Z',
      to: '2026-08-20T00:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }
    const last7d = { ...last30d, from: '2026-08-13T00:00:00.000Z' }
    const sort = { sortBy: 'gmv' as const, sortOrder: 'desc' as const }
    apiMocks.videos.mockImplementation((query: VideoQuery) =>
      Promise.resolve({
        apiVersion: 'v1',
        source: 'local_detail',
        range: {
          windowStart: query.from,
          windowEnd: query.to,
          shopTimezone: 'UTC',
          isPartial: false,
        },
        freshness: { isStale: false, asOf: '2026-08-19T07:30:00Z' },
        errors: [],
        data: [video(query.from, { views: 1 })],
      }),
    )
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 5 * 60 * 1000 } },
    })
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { rerender } = renderHook(({ query }) => useVideosQuery(query, sort), {
      initialProps: { query: last30d },
      wrapper,
    })
    await waitFor(() => expect(apiMocks.videos).toHaveBeenCalledTimes(1))

    rerender({ query: last7d })
    await waitFor(() => expect(apiMocks.videos).toHaveBeenCalledTimes(2))

    rerender({ query: last30d })
    await waitFor(() => expect(apiMocks.videos).toHaveBeenCalledTimes(3))
  })
})

function video(platformExternalId: string, fields: Record<string, unknown>) {
  return {
    platformExternalId,
    fields,
    sourceStatus: null,
    status: null,
    sourceUpdatedAt: null,
    observedAt: '2026-08-19T07:30:00Z',
  }
}
