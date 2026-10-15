import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DashboardQueryParams } from '../types/dashboard.types'
import { DashboardAffiliateRankings } from './dashboard-affiliate-rankings'

vi.mock('../queries/dashboard.queries', () => ({
  useDashboardAffiliateRankingsQuery: () => ({
    data: {
      period: { start: '2026-08-21', end: '2026-09-19' },
      days: 7,
      complete: true,
      shopCount: 1,
      expectedShopCount: 1,
      totalVideos: 1,
      totalProducts: 1,
      topVideos: [
        {
          id: 's:v',
          videoId: 'v',
          shopName: 'Shop',
          title: 'Video One',
          creatorUsername: 'alice',
          coverImageUrl: null,
          videoPostTime: null,
          gmvMinor: 500,
          views: 10,
        },
      ],
      topProducts: [
        {
          id: 's:p',
          productId: 'p',
          shopName: 'Shop',
          title: 'Toy',
          coverImageUrl: null,
          videoCount: 1,
          singleProductVideoGmvMinor: 1200,
          singleProductVideoItemsSold: 3,
        },
      ],
      productMetricScope: 'single_product_videos_only',
    },
    isPlaceholderData: false,
    isFetching: false,
    isError: false,
  }),
}))

Object.defineProperty(globalThis, 'ResizeObserver', {
  writable: true,
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  }),
})

const params: DashboardQueryParams = {
  currency: 'USD',
  timezone: 'America/Los_Angeles',
  realtimeRange: 'today',
  trendRange: 'last7d',
  orderRange: 'last7d',
}

describe('DashboardAffiliateRankings', () => {
  it('renders both rankings and the single-product-video scope', () => {
    render(<DashboardAffiliateRankings params={params} />)

    expect(screen.getByRole('heading', { name: /Top Videos/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Top Products/ })).toBeInTheDocument()
    expect(screen.getByText('Video One')).toBeInTheDocument()
    expect(screen.getByText('Toy')).toBeInTheDocument()
    expect(screen.getByText(/商品 GMV 与销量仅汇总单商品视频/)).toBeInTheDocument()
  })
})
