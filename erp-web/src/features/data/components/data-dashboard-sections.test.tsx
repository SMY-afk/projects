import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ContentRankingTable, MetricCards, TrendCard } from './data-dashboard-sections'

const envelope = {
  apiVersion: 'v1' as const,
  source: 'local_snapshot' as const,
  freshness: { isStale: false, asOf: '2026-08-17T00:00:00Z' },
  errors: [],
  data: [
    {
      metricSet: 'overview',
      granularity: 'day' as const,
      windowStart: '2026-08-16T07:00:00Z',
      windowEnd: '2026-08-17T07:00:00Z',
      currency: 'USD',
      metrics: {
        gmv: { amountMinor: 1690, currency: 'USD' },
        orders: 4,
        videoProductClicks: 25,
        liveCustomers: 1,
        latestLiveClickToOrderRate: 0.25,
      },
      sourceUpdatedAt: null,
      capturedAt: '2026-08-17T00:00:00Z',
    },
  ],
}

describe('data dashboard sections', () => {
  it('renders verified operating metrics instead of unavailable placeholders', () => {
    render(<MetricCards query={{ data: envelope, isLoading: false }} />)

    expect(screen.getByText(/16\.90/)).toBeInTheDocument()
    expect(screen.getByText('视频商品点击')).toBeInTheDocument()
    expect(screen.getByText('直播成交客户')).toBeInTheDocument()
    expect(screen.getByText('最近一日直播点击成交率')).toBeInTheDocument()
    expect(screen.queryByText('--')).not.toBeInTheDocument()
  })

  it('renders an amount trend with comparison, moving average, and summary metrics', () => {
    render(<TrendCard query={{ data: envelope, isLoading: false }} timezone="America/Los_Angeles" />)

    expect(screen.getByRole('img', { name: '成交金额趋势' })).toBeInTheDocument()
    expect(screen.getByText('成交金额')).toBeInTheDocument()
    expect(screen.getByText('日均成交额')).toBeInTheDocument()
    expect(screen.getByText('最高成交额')).toBeInTheDocument()
    expect(screen.getByText('最低成交额')).toBeInTheDocument()
    expect(screen.getByText('当前周期')).toBeInTheDocument()
    expect(screen.getByText('上一周期')).toBeInTheDocument()
    expect(screen.getByText('7 日平均')).toBeInTheDocument()
    expect(screen.queryByText('当前时间范围暂无趋势数据。')).not.toBeInTheDocument()
  })

  it('shows the requested range while video data is syncing instead of an empty table', () => {
    render(
      <ContentRankingTable
        kind="video"
        query={{
          data: { ...envelope, data: [], freshness: { isStale: true } },
          isLoading: false,
        }}
        sort={{ sortBy: 'gmv', sortOrder: 'desc' }}
        onSortChange={() => undefined}
        pendingText="正在获取 2026-08-01 至 2026-08-15 的视频数据……"
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('正在获取 2026-08-01 至 2026-08-15 的视频数据……')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows the latest TikTok date when today has no available data', () => {
    render(
      <ContentRankingTable
        kind="video"
        query={{
          data: {
            ...envelope,
            source: 'local_detail',
            data: [],
            freshness: { isStale: false, asOf: '2026-08-19T07:53:00Z' },
          },
          isLoading: false,
        }}
        sort={{ sortBy: 'gmv', sortOrder: 'desc' }}
        onSortChange={() => undefined}
        unavailableText="今日暂无数据 · TikTok 数据目前更新至 2026-08-17"
      />,
    )

    expect(screen.getByText('今日暂无数据 · TikTok 数据目前更新至 2026-08-17')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('keeps a video load error visible and does not render retained data from another range', () => {
    render(
      <ContentRankingTable
        kind="video"
        query={{
          data: {
            ...envelope,
            data: [
              {
                platformExternalId: 'old-video',
                fields: { title: '其他时间范围旧数据', views: 999, gmvAmount: '999.00' },
                sourceStatus: null,
                status: null,
                sourceUpdatedAt: null,
                observedAt: '2026-08-18T00:00:00Z',
              },
            ],
          },
          error: new Error('network failed'),
          isError: true,
          isLoading: false,
        }}
        sort={{ sortBy: 'gmv', sortOrder: 'desc' }}
        onSortChange={() => undefined}
      />,
    )

    expect(screen.getByText('视频数据加载失败')).toBeInTheDocument()
    expect(screen.queryByText('其他时间范围旧数据')).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
