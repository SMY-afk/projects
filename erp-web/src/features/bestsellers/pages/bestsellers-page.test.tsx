import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BestsellerFreshness, BestsellerSafeError } from '../types/bestseller.types'
import BestsellersPage from './bestsellers-page'

const listQuery = vi.fn()
const authorizationQuery = vi.fn()
const syncMutation = vi.fn()
const authorizationRefetch = vi.fn()
const listRefetch = vi.fn()

function rankingResult(entity = 'products') {
  const freshness: BestsellerFreshness = { isStale: false, asOf: '2026-08-20T04:00:00Z' }
  const errors: BestsellerSafeError[] = []

  return {
    data: {
      data: {
        query: {},
        items: [
          {
            entityType: entity.slice(0, -1),
            externalId: `${entity}-1`,
            rank: 1,
            displayName: `${entity} item`,
            gmv: { raw: '$1K-$2K', currencyContext: 'USD', computable: false },
            extensions: { followers_count: 1200, likes_count: 300 },
          },
        ],
      },
      freshness,
      errors,
    },
    isLoading: false,
    isError: false,
    refetch: listRefetch,
  }
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-search">{location.search}</output>
}

vi.mock('@/auth/use-auth', () => ({ useAuth: () => ({ hasPermissions: () => true }) }))
vi.mock('../api/bestsellers.api', () => ({ isBestsellersMock: false }))
vi.mock('../config/bestseller-rollout', () => ({
  bestsellerRolloutConfig: { stage: 'all' },
  shopIsInBestsellerRollout: () => true,
}))
vi.mock('../queries/bestseller.queries', () => ({
  useBestsellerShopsQuery: () => ({
    data: [{ id: 'shop-1', shopName: 'Akeleo Fun Toys', timezone: 'America/Los_Angeles' }],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useBestsellerAuthorizationQuery: () => authorizationQuery() as unknown,
  useBestsellerListQuery: (...args: unknown[]) => listQuery(...args) as unknown,
  useBestsellerSyncMutation: () => syncMutation() as unknown,
  useBestsellerReauthorizationMutation: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
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
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  })
})

beforeEach(() => {
  listQuery.mockReset()
  authorizationQuery.mockReset()
  syncMutation.mockReset()
  authorizationRefetch.mockReset()
  listRefetch.mockReset()
  listQuery.mockImplementation((_query, entity: string) => rankingResult(entity))
  authorizationQuery.mockReturnValue({
    data: {
      data: {
        shopId: 'shop-1',
        status: 'ready',
        requiredScopes: ['data.bestselling.public.read'],
        grantedScopes: ['data.bestselling.public.read'],
        missingScopes: [],
        canRead: true,
      },
      freshness: { isStale: false, asOf: '2026-08-20T04:00:00Z' },
      errors: [],
    },
    isLoading: false,
    isError: false,
    refetch: authorizationRefetch,
  })
  syncMutation.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false })
})

describe('BestsellersPage', () => {
  it('renders filters, scope status, sync status and switches four entity tables', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1&date=2026-08-19&timeSlot=7D']}>
        <BestsellersPage />
        <LocationProbe />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '畅销榜' })).toBeInTheDocument()
    expect(screen.getByLabelText('店铺')).toBeInTheDocument()
    expect(screen.getByLabelText('结束日期')).toBeInTheDocument()
    expect(screen.getByLabelText('统计周期')).toBeInTheDocument()
    expect(screen.queryByText('Scope 已就绪')).not.toBeInTheDocument()
    expect(screen.getByText('数据已更新')).toBeInTheDocument()
    for (const tab of ['商品榜', '创作者榜', '视频榜', '直播榜']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument()
    }
    expect(screen.getByRole('columnheader', { name: '商品' })).toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: '创作者榜' }))

    expect(screen.getByRole('columnheader', { name: '粉丝数' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '获赞数' })).toBeInTheDocument()
    await waitFor(() => {
      const query = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '')
      expect(query.get('tab')).toBe('creators')
      expect(query.get('authorType')).toBe('ALL')
    })
  })

  it('writes resolved defaults to the URL for sharing and reload recovery', async () => {
    render(
      <MemoryRouter initialEntries={['/bestsellers']}>
        <BestsellersPage />
        <LocationProbe />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const query = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '')
      expect(query.get('shopId')).toBe('shop-1')
      expect(query.get('tab')).toBe('products')
      expect(query.get('date')).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(query.get('timeSlot')).toBe('7D')
      expect(query.get('currency')).toBe('USD')
    })
  })

  it('clamps an incomplete shop-local date to the latest completed date', async () => {
    vi.setSystemTime(new Date('2026-08-21T02:45:00Z'))
    render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1&date=2026-08-20']}>
        <BestsellersPage />
        <LocationProbe />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const query = new URLSearchParams(screen.getByTestId('location-search').textContent ?? '')
      expect(query.get('date')).toBe('2026-08-19')
    })
    vi.useRealTimers()
  })

  it('refreshes both authorization status and the active ranking', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /刷新/ }))
    expect(authorizationRefetch).toHaveBeenCalledOnce()
    expect(listRefetch).toHaveBeenCalledOnce()
  })

  it('separates missing authorization from ranking loading and disables the read query', () => {
    authorizationQuery.mockReturnValue({
      data: {
        data: {
          shopId: 'shop-1',
          status: 'reauthorization_required',
          requiredScopes: ['data.bestselling.public.read'],
          grantedScopes: [],
          missingScopes: ['data.bestselling.public.read'],
          canRead: false,
        },
        freshness: { isStale: false },
        errors: [],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    listQuery.mockReturnValue({ isLoading: false, isError: false, refetch: vi.fn() })

    render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('需要重新授权店铺')).toBeInTheDocument()
    expect(screen.getByText('缺少畅销榜读取授权')).toBeInTheDocument()
    expect(listQuery.mock.calls.at(-1)?.[2]).toBe(false)
  })

  it('renders loading, empty and real-mode error as distinct content states', () => {
    listQuery.mockReturnValue({ isLoading: true, isError: false, refetch: vi.fn() })
    const { rerender } = render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('正在加载榜单')).toBeInTheDocument()

    listQuery.mockReturnValue({
      data: {
        data: { query: {}, items: [] },
        freshness: { isStale: false, asOf: '2026-08-20T04:00:00Z' },
        errors: [],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    rerender(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('当前筛选组合暂无榜单')).toBeInTheDocument()

    listQuery.mockReturnValue({
      data: {
        data: { query: {}, items: [] },
        freshness: { isStale: true, asOf: null },
        errors: [{ code: 'data_unavailable', message: 'No snapshot.', action: 'resync' }],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })
    rerender(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('尚未同步')).toBeInTheDocument()
    expect(screen.getByText('尚无本地快照')).toBeInTheDocument()
    expect(screen.getByText('尚无已同步榜单')).toBeInTheDocument()
    expect(screen.queryByText('数据可能过期')).not.toBeInTheDocument()

    const staleRanking = rankingResult()
    staleRanking.data.freshness = {
      isStale: true,
      asOf: '2026-08-20T04:00:00Z',
      lastErrorAt: '2026-08-21T04:00:00Z',
    }
    staleRanking.data.errors = [{ code: 'sync_failed', message: 'The last refresh failed.', action: 'resync' }]
    listQuery.mockReturnValue(staleRanking)
    rerender(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('数据可能过期')).toHaveLength(2)
    expect(screen.queryByText('尚未同步')).not.toBeInTheDocument()

    listQuery.mockReturnValue({
      error: new Error('backend unavailable'),
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    })
    rerender(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )
    expect(screen.getByText('无法读取本地畅销榜快照，请稍后重试。')).toBeInTheDocument()
    expect(screen.queryByText('Construction Truck Set')).not.toBeInTheDocument()
  })

  it('shows synchronization separately while keeping the last successful snapshot visible', () => {
    syncMutation.mockReturnValue({ mutate: vi.fn(), isPending: true, isError: false })

    render(
      <MemoryRouter initialEntries={['/bestsellers?shopId=shop-1']}>
        <BestsellersPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('正在提交同步任务')).toBeInTheDocument()
    expect(screen.getByText('榜单同步中')).toBeInTheDocument()
    expect(screen.getByText('products item')).toBeInTheDocument()
  })
})
