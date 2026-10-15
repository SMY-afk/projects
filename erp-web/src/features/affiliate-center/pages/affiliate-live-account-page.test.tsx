import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import AffiliateLiveAccountPage from './affiliate-live-account-page'

const api = vi.hoisted(() => ({
  listLiveAccounts: vi.fn(),
  listShops: vi.fn(),
  syncLiveAccounts: vi.fn(),
}))

vi.mock('../api/affiliate-center.api', () => ({ affiliateCenterApi: api }))

describe('AffiliateLiveAccountPage', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
  })

  beforeEach(() => {
    vi.clearAllMocks()
    api.listShops.mockResolvedValue([
      { id: 'shop-1', shopName: 'Akeleo Toys', timezone: 'America/Los_Angeles', currency: 'USD' },
    ])
    api.listLiveAccounts.mockResolvedValue({
      apiVersion: 'v1',
      source: 'local_detail',
      data: [
        {
          platformExternalId: 'live-1',
          fields: {
            accountType: 'AFFILIATE_ACCOUNTS',
            username: '@creator-one',
            title: '联盟直播专场',
            gmvAmount: '128.50',
            gmvCurrency: 'USD',
            skuOrders: 12,
            views: 574,
            clickThroughRate: '0.0417',
          },
          sourceStatus: 'ended',
          status: 'ended',
          sourceUpdatedAt: '2026-09-01T00:00:00Z',
          observedAt: '2026-09-02T00:00:00Z',
        },
      ],
      freshness: { isStale: false, asOf: '2026-09-02T00:00:00Z' },
      errors: [],
      pagination: { page: 1, pageSize: 50, total: 126 },
    })
    api.syncLiveAccounts.mockResolvedValue({
      items: [{ jobId: 'live-job-1', status: 'queued', existing: false }],
      captureMode: 'official_api_owned',
    })
  })

  it('loads only the dedicated affiliate live-account endpoint', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/affiliate-center/live-accounts?shopId=shop-1']}>
        <AffiliateLiveAccountPage />
      </MemoryRouter>,
    )

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual(['达人', '所有视频', '联盟账号直播数据'])
    expect(screen.getByRole('tab', { name: '联盟账号直播数据' })).toHaveAttribute('aria-selected', 'true')
    expect(await screen.findByText('联盟直播专场')).toBeInTheDocument()
    expect(screen.getByText('@creator-one')).toBeInTheDocument()
    expect(screen.getByText('574')).toBeInTheDocument()
    expect(screen.getByText('4.17%')).toBeInTheDocument()
    await waitFor(() =>
      expect(api.listLiveAccounts).toHaveBeenCalledWith({
        shopId: 'shop-1',
        page: 1,
        pageSize: 50,
        preset: 'last7d',
        sortBy: 'gmv',
        sortOrder: 'desc',
      }),
    )

    expect(await screen.findByText('共 126 条')).toBeInTheDocument()
    expect(await screen.findByTitle('2')).toBeInTheDocument()

    expect(['今天', '近 7 天', '近 1 个月', '近 2 个月'].every((label) => screen.getByText(label))).toBe(true)
    await user.click(screen.getByText('近 2 个月'))
    await waitFor(() =>
      expect(api.listLiveAccounts).toHaveBeenLastCalledWith(
        expect.objectContaining({ shopId: 'shop-1', preset: 'last60d' }),
      ),
    )
  })

  it('submits an official sync for the selected shop and range', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter
        initialEntries={[
          '/affiliate-center/live-accounts?shopId=shop-1&livePreset=custom&customFrom=2026-08-01&customTo=2026-08-15',
        ]}
      >
        <AffiliateLiveAccountPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /同步最新数据/ }))

    await waitFor(() =>
      expect(api.syncLiveAccounts).toHaveBeenCalledWith({
        shopId: 'shop-1',
        preset: 'custom',
        customFrom: '2026-08-01',
        customTo: '2026-08-15',
      }),
    )
    expect(await screen.findByText(/同步任务已提交/)).toBeInTheDocument()
  })
})
