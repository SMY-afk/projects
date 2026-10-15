import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import DataPage from './data-page'

const refetch = vi.fn()
const allRollout = { stage: 'all' as const, testShopIds: new Set<string>() }

vi.mock('@/auth/use-auth', () => ({ useAuth: () => ({ hasPermissions: () => true }) }))
vi.mock('../queries/data.queries', () => ({
  useDataShopOptionsQuery: () => ({
    data: [{ id: 'shop-1', shopName: '测试店铺', timezone: 'Asia/Shanghai' }],
    isLoading: false,
    isError: false,
    refetch,
  }),
  useOverviewQuery: () => ({
    data: { freshness: { isStale: true }, data: [], errors: [] },
    isLoading: false,
    isError: false,
    refetch,
  }),
  useTrendsQuery: () => ({
    data: { freshness: { isStale: true }, data: [], errors: [] },
    isLoading: false,
    isError: false,
    refetch,
  }),
  useVideosQuery: () => ({
    data: {
      freshness: { isStale: false, asOf: '2026-08-19T07:30:00Z' },
      range: {
        windowStart: '2026-07-20T16:00:00Z',
        windowEnd: '2026-08-19T16:00:00Z',
        shopTimezone: 'Asia/Shanghai',
        isPartial: true,
      },
      data: [
        {
          platformExternalId: '9706296717045718228',
          fields: {
            title: '爆款视频',
            creatorNickname: '示例达人',
            creatorOpenId: 's9NNQwAAAACvfWKwPW83JHUJYNnIl2DbnAf__c7NFFBnEZVYnURnww',
            creatorUsername: 'creator_user',
            creatorAuthorType: 'AFFILIATE',
            gmvAmount: '128.50',
            gmvCurrency: 'USD',
            gpmAmount: '12.80',
            gpmCurrency: 'USD',
            views: 12500,
            clickThroughRate: '0.125',
            averageCustomers: 8,
            durationSeconds: 34,
            completionRate: '0.001761',
            retention2sRate: '0.077947',
            retention6sRate: '0.032319',
            retention25Rate: '0.025',
            retention50Rate: '0.015',
            retention75Rate: '0.008',
            retention100Rate: '0.001761',
            coverImageUrl: 'https://example.test/video-1.jpg',
            hashTags: ['toys', 'demo'],
            promotedProducts: [
              { id: 'product-1', name: 'Demo product', imageUrl: 'https://example.test/product-1.jpg' },
            ],
            videoPostTime: '2026-08-16T00:00:00Z',
          },
          sourceStatus: 'published',
          status: 'published',
          sourceUpdatedAt: null,
          observedAt: '2026-08-17T00:00:00Z',
        },
      ],
      errors: [],
    },
    isLoading: false,
    isError: false,
    refetch,
  }),
  useLivesQuery: () => ({
    data: {
      freshness: { isStale: false },
      data: [
        {
          platformExternalId: '9676769683151005733',
          fields: {
            title: '联盟达人直播',
            username: 'affiliate_host',
            accountType: 'AFFILIATE_ACCOUNTS',
            gmvAmount: '320.50',
            gmvCurrency: 'USD',
            createdSkuOrders: 9,
            skuOrders: 7,
            itemsSold: 8,
            customers: 6,
            averagePriceAmount: '53.42',
            averagePriceCurrency: 'USD',
            productsAdded: 12,
            differentProductsSold: 4,
            clickToOrderRate: '25%',
            startTime: '1786932000',
            endTime: '1786935600',
          },
          sourceStatus: null,
          status: null,
          sourceUpdatedAt: null,
          observedAt: '2026-08-17T00:00:00Z',
        },
        {
          platformExternalId: '9556634612373717404',
          fields: {
            title: '官方账号直播',
            username: 'official_host',
            accountType: 'OFFICIAL_ACCOUNTS',
            gmvAmount: '80.00',
            gmvCurrency: 'USD',
            createdSkuOrders: 3,
            skuOrders: 2,
            itemsSold: 2,
            customers: 2,
            averagePriceAmount: '40.00',
            averagePriceCurrency: 'USD',
            productsAdded: 5,
            differentProductsSold: 2,
            clickToOrderRate: '0.2',
            views: 2000,
            likes: 320,
            comments: 18,
            clickThroughRate: '0.085',
            startTime: '1786924800',
            endTime: '1786928400',
          },
          sourceStatus: null,
          status: null,
          sourceUpdatedAt: null,
          observedAt: '2026-08-17T00:00:00Z',
        },
      ],
      errors: [],
    },
    isLoading: false,
    isError: false,
    refetch,
  }),
  useSyncStatusQuery: () => ({
    data: { freshness: { isStale: true }, data: [], errors: [] },
    isLoading: false,
    isError: false,
    refetch,
  }),
  useSyncHealthQuery: () => ({
    data: [],
    isLoading: false,
    isError: false,
    refetch,
  }),
  useResyncMutation: () => ({ isPending: false, isError: false, mutate: vi.fn() }),
}))

beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-08-19T08:00:00.000Z'))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('DataPage', () => {
  it('keeps the filters compact and preserves KPI and trend frames when snapshots are unavailable', () => {
    render(<DataPage rollout={allRollout} />)

    expect(screen.getByRole('heading', { name: '数据' })).toBeInTheDocument()
    expect(screen.getByLabelText('店铺')).toBeInTheDocument()
    expect(screen.getAllByLabelText('日期范围')).toHaveLength(2)
    expect(screen.getByLabelText('粒度')).toBeInTheDocument()
    expect(screen.getByLabelText('币种')).toBeInTheDocument()
    expect(screen.getByText('今天')).toBeInTheDocument()
    expect(screen.getByText('最近7天')).toBeInTheDocument()
    expect(screen.getByText('最近30天')).toBeInTheDocument()
    expect(screen.getByText('最近30天').closest('label')?.querySelector('input')).toBeChecked()
    expect(screen.getByText('自定义时间')).toBeInTheDocument()
    expect(screen.getByText('统计区间：2026-07-21 ～ 2026-08-19 · 更新至 15:30')).toBeInTheDocument()

    const resyncButton = screen.getByRole('button', { name: '重新同步' })
    const refreshButton = screen.getByRole('button', { name: /刷新本地数据/ })
    expect(resyncButton).toHaveClass('ant-btn-primary')
    expect(refreshButton).not.toHaveClass('ant-btn-primary')

    const metrics = screen.getByRole('heading', { name: '核心指标' }).closest('section')
    expect(metrics).not.toBeNull()
    expect(within(metrics!).getByText('成交金额')).toBeInTheDocument()
    expect(within(metrics!).getByText('成交订单')).toBeInTheDocument()
    expect(within(metrics!).getByText('视频商品点击')).toBeInTheDocument()
    expect(within(metrics!).getByText('直播成交客户')).toBeInTheDocument()
    expect(within(metrics!).getByText('最近一日直播点击成交率')).toBeInTheDocument()
    expect(within(metrics!).getAllByText('--')).toHaveLength(5)
    expect(screen.getByRole('img', { name: '趋势图表空状态' })).toBeInTheDocument()
    expect(screen.getAllByText('暂无本地快照，重新同步后将在此展示。').length).toBeGreaterThanOrEqual(2)
  })

  it('shows operating fields in rankings and moves technical fields into data status', () => {
    render(<DataPage rollout={allRollout} />)

    const videoCard = screen.getByText('视频数据').closest('.ant-card')
    expect(videoCard).toBeInstanceOf(HTMLElement)
    if (!(videoCard instanceof HTMLElement)) throw new Error('视频数据卡片未渲染')
    expect(within(videoCard).getAllByText('视频').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('视频 ID').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('播放量（所选时间）').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('商品点击率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('日均客户数').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('GMV').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('GPM').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('2秒停留率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('6秒停留率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('25%停留率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('50%停留率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('75%停留率').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('100%停留率').length).toBeGreaterThan(0)
    expect(
      within(videoCard).getAllByText('GMV')[0].closest('th')?.querySelector('.ant-table-column-sorter'),
    ).not.toBeNull()
    expect(
      within(videoCard).getAllByText('GPM')[0].closest('th')?.querySelector('.ant-table-column-sorter'),
    ).not.toBeNull()
    expect(
      within(videoCard).getAllByText('发布时间')[0].closest('th')?.querySelector('.ant-table-column-sorter'),
    ).not.toBeNull()
    expect(within(videoCard).queryAllByText('创作者 Open ID')).toHaveLength(0)
    expect(within(videoCard).getAllByText('创作者用户名').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('创作者昵称').length).toBeGreaterThan(0)
    expect(within(videoCard).getAllByText('账号类型').length).toBeGreaterThan(0)
    expect(
      within(videoCard).getAllByText('账号类型')[0].closest('th')?.querySelector('.ant-table-filter-trigger'),
    ).not.toBeNull()
    expect(within(videoCard).getAllByText('推广商品').length).toBeGreaterThan(0)
    expect(within(videoCard).getByText('爆款视频')).toBeInTheDocument()
    expect(within(videoCard).getByText('9706296717045718228')).toBeInTheDocument()
    expect(within(videoCard).getByText('12,500')).toBeInTheDocument()
    expect(within(videoCard).getByText('12.5%')).toBeInTheDocument()
    expect(within(videoCard).getByText('00:34')).toBeInTheDocument()
    expect(within(videoCard).getByText('0.18%')).toBeInTheDocument()
    expect(within(videoCard).getByText('7.79%')).toBeInTheDocument()
    expect(within(videoCard).getByText('3.23%')).toBeInTheDocument()
    expect(within(videoCard).getByText('2.5%')).toBeInTheDocument()
    expect(within(videoCard).getByText('1.5%')).toBeInTheDocument()
    expect(within(videoCard).getByText('0.8%')).toBeInTheDocument()
    expect(within(videoCard).getByText('#toys')).toBeInTheDocument()
    expect(within(videoCard).getByText('creator_user')).toBeInTheDocument()
    expect(within(videoCard).getByText('联盟达人')).toBeInTheDocument()
    const videoHeaders = Array.from(videoCard.querySelectorAll('thead tr:last-child th'))
      .map((header) => header.textContent?.trim())
      .filter(Boolean)
    expect(videoHeaders.indexOf('创作者昵称')).toBeLessThan(videoHeaders.indexOf('创作者用户名'))
    expect(videoHeaders.indexOf('创作者用户名')).toBeLessThan(videoHeaders.indexOf('视频'))
    expect(within(videoCard).queryByRole('img', { name: '爆款视频' })).not.toBeInTheDocument()
    expect(within(videoCard).getByRole('img', { name: 'Demo product' })).toHaveAttribute(
      'src',
      'https://example.test/product-1.jpg',
    )
    expect(within(videoCard).queryByText('Demo product')).not.toBeInTheDocument()
    expect(within(videoCard).queryByText('product-1')).not.toBeInTheDocument()
    expect(within(videoCard).getByText('爆款视频')).toHaveClass('data-video-title')
    expect(videoCard.querySelector('.ant-table-body')).toHaveStyle({ maxHeight: '520px' })
    expect(within(videoCard).queryByText('平台内容 ID')).not.toBeInTheDocument()
    expect(within(videoCard).queryByText('来源状态')).not.toBeInTheDocument()

    const liveCard = screen.getByText('直播数据').closest('.ant-card')
    expect(liveCard).toBeInstanceOf(HTMLElement)
    if (!(liveCard instanceof HTMLElement)) throw new Error('直播数据卡片未渲染')
    expect(
      within(liveCard).getAllByText('GMV')[0].closest('th')?.querySelector('.ant-table-column-sorter'),
    ).not.toBeNull()
    expect(within(liveCard).getAllByText('直播 ID').length).toBeGreaterThan(0)
    expect(within(liveCard).getByText('9676769683151005733')).toBeInTheDocument()
    const liveHeaders = Array.from(liveCard.querySelectorAll('thead th'))
      .map((header) => header.textContent?.trim())
      .filter(Boolean)
    expect(liveHeaders.indexOf('主播账号')).toBeLessThan(liveHeaders.indexOf('直播场次'))
    expect(liveHeaders.indexOf('直播场次')).toBeLessThan(liveHeaders.indexOf('直播 ID'))
    expect(
      within(liveCard).getAllByText('开播时间')[0].closest('th')?.querySelector('.ant-table-column-sorter'),
    ).not.toBeNull()
    expect(within(liveCard).getAllByText('销售数据').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('互动数据（官方/营销号）').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('创建订单').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('支付订单').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('下单客户').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('观看次数').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('点赞数').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('评论数').length).toBeGreaterThan(0)
    expect(within(liveCard).getAllByText('商品点击率').length).toBeGreaterThan(0)
    expect(within(liveCard).getByText('联盟达人')).toBeInTheDocument()
    expect(within(liveCard).getByText('官方账号')).toBeInTheDocument()
    expect(within(liveCard).getByText('2,000')).toBeInTheDocument()
    expect(within(liveCard).getByText('320')).toBeInTheDocument()
    expect(within(liveCard).getByText('18')).toBeInTheDocument()
    expect(within(liveCard).getByText('25%')).toBeInTheDocument()
    expect(within(liveCard).getByText('8.5%')).toBeInTheDocument()
    expect(within(liveCard).getAllByText('不适用')).toHaveLength(4)
    expect(liveCard.querySelector('.ant-table-body')).toHaveStyle({ maxHeight: '520px' })

    expect(screen.getByText('数据状态')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '同步健康' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '同步日志' })).toBeInTheDocument()
    expect(screen.getAllByText('平台内容 ID').length).toBeGreaterThan(0)
    expect(screen.getAllByText('来源状态').length).toBeGreaterThan(0)
    expect(screen.getAllByText('9706296717045718228').length).toBeGreaterThan(1)
    const statusCard = screen.getByText(/数据状态与同步记录/).closest('.ant-card')
    expect(statusCard).toHaveClass('data-status-card')
    expect(statusCard?.querySelector('.data-status-table .ant-table-body')).toHaveStyle({ maxHeight: '360px' })
  })
})
