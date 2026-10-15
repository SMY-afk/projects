import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { HttpError } from '@/services/http-client'
import AffiliateCenterPage from './affiliate-center-page'

const api = vi.hoisted(() => ({
  listResources: vi.fn(),
  listShops: vi.fn(),
  listCreatorMetrics: vi.fn(),
  listVideos: vi.fn(),
  getSyncStatus: vi.fn(),
  sync: vi.fn(),
}))

const onlineBrowser = {
  state: 'online',
  cdpAvailable: true,
  sessionAvailable: true,
  updatedAt: '2026-08-28T01:00:00Z',
  recoveredAt: null,
  latestAvailableDate: null,
}

vi.mock('../api/affiliate-center.api', () => ({ affiliateCenterApi: api }))
vi.mock('../components/creator-metric-table', () => ({ CreatorMetricTable: () => <div>达人指标表</div> }))

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="当前地址">{`${location.pathname}${location.search}`}</output>
}

describe('AffiliateCenterPage routes', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
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
    api.listResources.mockResolvedValue({
      items: [
        { key: 'creators', label: '达人' },
        { key: 'videos', label: '所有视频' },
      ],
      queryDimensions: ['shopId', 'windowStart', 'windowEnd', 'shopTimezone', 'currency', 'filters'],
      display: {
        creators: { metrics: [] },
        videos: { metrics: [] },
      },
    })
    api.listShops.mockResolvedValue([])
    api.listCreatorMetrics.mockResolvedValue({ report: null, items: [], total: 0 })
    api.listVideos.mockResolvedValue({ run: null, items: [], total: 0 })
    api.getSyncStatus.mockResolvedValue({ items: [], browser: onlineBrowser })
    api.sync.mockResolvedValue({ items: [], captureMode: 'browser_daemon_owned' })
  })

  afterEach(() => vi.useRealTimers())

  it('keeps an existing date range fixed when TikTok availability advances', async () => {
    api.getSyncStatus.mockResolvedValue({
      items: [],
      browser: { ...onlineBrowser, latestAvailableDate: '2026-08-29' },
    })
    api.listCreatorMetrics.mockResolvedValue({ report: { status: 'complete' }, items: [], total: 0 })
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-21&to=2026-08-27&currency=USD']}
      >
        <Routes>
          <Route
            element={
              <>
                <LocationProbe />
                <AffiliateCenterPage />
              </>
            }
            path="/affiliate-center/:resource"
          />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.listCreatorMetrics).toHaveBeenCalled())
    expect(await screen.findByText(/所选范围完整快照更新时间/)).toBeInTheDocument()
    expect(screen.getByLabelText('当前地址')).toHaveTextContent('from=2026-08-21&to=2026-08-27')
  })

  it('does not present a heartbeat or another window run as the selected snapshot freshness', async () => {
    api.getSyncStatus.mockResolvedValue({
      items: [
        {
          resource: 'videos',
          resourceType: 'affiliate_video',
          status: 'succeeded',
          latestRun: { status: 'succeeded', finishedAt: '2026-09-24T07:00:00Z' },
        },
      ],
      latestAvailableDates: { videos: '2026-09-20' },
      browser: { ...onlineBrowser, updatedAt: '2026-09-24T08:00:00Z' },
    })
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-09-17&to=2026-09-23&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('当前已知可查询至：2026-09-20')).toBeInTheDocument()
    expect(screen.getByText('所选范围完整快照更新时间：暂无数据')).toBeInTheDocument()
  })

  it('moves Today to the TikTok actual latest available day', async () => {
    api.getSyncStatus.mockResolvedValue({
      items: [],
      browser: {
        ...onlineBrowser,
        latestAvailableDates: { creators: '2026-08-29' },
      },
    })
    api.listCreatorMetrics.mockResolvedValue({ report: { status: 'complete' }, items: [], total: 0 })
    render(
      <MemoryRouter
        initialEntries={[
          '/affiliate-center/creators?shopId=shop-1&from=2026-08-28&to=2026-08-28&currency=USD&creatorToday=1',
        ]}
      >
        <Routes>
          <Route
            element={
              <>
                <LocationProbe />
                <AffiliateCenterPage />
              </>
            }
            path="/affiliate-center/:resource"
          />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByLabelText('当前地址')).toHaveTextContent('creatorFrom=2026-08-29&creatorTo=2026-08-29'),
    )
  })

  it('submits creator-only synchronization with the URL-backed filters', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-01&to=2026-08-07&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /同步联盟达人/ }))

    await waitFor(() =>
      expect(api.sync).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-01',
        to: '2026-08-07',
        currency: 'USD',
        resources: ['creators'],
      }),
    )
    expect(screen.queryByText(/导入达人 Excel/)).not.toBeInTheDocument()
    expect(await screen.findByText('同步请求已提交，请在同步状态中查看进度。')).toBeInTheDocument()
  })

  it('automatically syncs a selected window when no complete report exists', async () => {
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-25&to=2026-08-25&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(api.sync).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-25',
        to: '2026-08-25',
        currency: 'USD',
        resources: ['creators'],
      }),
    )
    expect(
      await screen.findByText('所选日期缺少逐日快照，已只提交缺失日期；补齐后将自动显示汇总。'),
    ).toBeInTheDocument()
  })

  it('clears the automatic backfill notice after the selected report becomes complete', async () => {
    let reportIsComplete = false
    let runStatus = 'running'
    api.listCreatorMetrics.mockImplementation(() =>
      Promise.resolve({ report: reportIsComplete ? { status: 'complete' } : null, items: [], total: 0 }),
    )
    api.sync.mockResolvedValue({
      items: [
        {
          runId: 'run-backfill',
          resource: 'creators',
          resourceType: 'affiliate_creator',
          status: 'queued',
          existing: false,
        },
      ],
      captureMode: 'browser_daemon_owned',
    })
    api.getSyncStatus.mockImplementation(() =>
      Promise.resolve({
        browser: onlineBrowser,
        items: [
          {
            resource: 'creators',
            resourceType: 'affiliate_creator',
            status: runStatus,
            latestRun: { runId: 'run-backfill', status: runStatus },
          },
        ],
      }),
    )

    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-25&to=2026-08-25&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.sync).toHaveBeenCalled())
    const notice = await screen.findByText(/所选日期缺少逐日快照/)
    expect(notice).toBeInTheDocument()

    const incompleteLoadCount = api.listCreatorMetrics.mock.calls.length
    reportIsComplete = true
    runStatus = 'succeeded'
    await waitFor(() => expect(api.listCreatorMetrics.mock.calls.length).toBeGreaterThan(incompleteLoadCount), {
      timeout: 4_000,
    })
    await waitFor(() => expect(screen.queryByText(notice.textContent ?? '')).not.toBeInTheDocument())
  })

  it('automatically syncs an exact video day when its snapshot is missing', async () => {
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-08-22&to=2026-08-22&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(api.sync).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-22',
        to: '2026-08-22',
        currency: 'USD',
        resources: ['videos'],
      }),
    )
    expect(screen.getByRole('button', { name: /同步所有视频/ })).toBeInTheDocument()
  })

  it('retries a video window when its automatic intent fails before polling sees it active', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    api.sync
      .mockResolvedValueOnce({
        items: [
          {
            runId: 'run-1',
            resource: 'videos',
            resourceType: 'affiliate_video',
            status: 'queued',
            existing: false,
          },
        ],
        captureMode: 'browser_daemon_owned',
      })
      .mockResolvedValueOnce({
        items: [
          {
            runId: 'run-2',
            resource: 'videos',
            resourceType: 'affiliate_video',
            status: 'queued',
            existing: false,
          },
        ],
        captureMode: 'browser_daemon_owned',
      })
    api.getSyncStatus.mockResolvedValue({
      browser: onlineBrowser,
      items: [
        {
          resource: 'videos',
          resourceType: 'affiliate_video',
          status: 'failed',
          latestRun: {
            runId: 'run-1',
            status: 'failed',
            fetchedCount: 0,
            persistedCount: 0,
            startedAt: '2026-08-28T01:00:00Z',
            finishedAt: '2026-08-28T01:00:01Z',
            freshAt: null,
            errorCategory: 'window_not_settable',
            errorSummary: 'window failed',
          },
          lastFailureRun: null,
          lastCompleteRunId: null,
          lastCompleteAt: null,
        },
      ],
    })

    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-08-19&to=2026-08-25&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.sync).toHaveBeenCalledTimes(1))
    await act(async () => vi.advanceTimersByTimeAsync(2_000))

    await waitFor(() => expect(api.sync).toHaveBeenCalledTimes(2))
  })

  it('hides an older failure after the selected window has a complete snapshot', async () => {
    api.listVideos.mockResolvedValue({
      run: { runId: 'complete-run', status: 'succeeded' },
      items: [],
      total: 0,
    })
    api.getSyncStatus.mockResolvedValue({
      browser: onlineBrowser,
      items: [
        {
          resource: 'videos',
          resourceType: 'affiliate_video',
          status: 'failed',
          latestRun: {
            runId: 'old-failure',
            status: 'failed',
            errorCategory: 'unknown_test_failure',
            errorSummary: 'stale failure',
          },
          lastFailureRun: null,
        },
      ],
    })

    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-08-19&to=2026-08-25&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.listVideos).toHaveBeenCalled())
    expect(screen.queryByText(/stale failure/)).not.toBeInTheDocument()
  })

  it('shows the actual 422 availability reason instead of blaming the daemon', async () => {
    api.listVideos.mockResolvedValue({
      run: { runId: 'complete-run', status: 'succeeded' },
      items: [],
      total: 0,
    })
    api.getSyncStatus.mockResolvedValue({
      items: [],
      browser: onlineBrowser,
    })
    api.sync.mockRejectedValue(
      new HttpError('TikTok Affiliate data is available through 2026-08-28.', { kind: 'http', status: 422 }),
    )

    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-08-23&to=2026-08-29&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /同步所有视频/ }))
    expect(await screen.findByText(/目前可同步至 2026-08-28/)).toBeInTheDocument()
    expect(screen.queryByText(/daemon 状态/)).not.toBeInTheDocument()
  })

  it('polls an active sync and reloads creator data after it succeeds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    api.getSyncStatus
      .mockResolvedValueOnce({ items: [{ resource: 'creators', status: 'running' }], browser: onlineBrowser })
      .mockResolvedValueOnce({ items: [{ resource: 'creators', status: 'succeeded' }], browser: onlineBrowser })
      .mockResolvedValue({ items: [{ resource: 'creators', status: 'succeeded' }], browser: onlineBrowser })
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-16&to=2026-08-24&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.getSyncStatus).toHaveBeenCalledTimes(1))
    const firstLoadCount = api.listCreatorMetrics.mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(2_000))

    await waitFor(() => expect(api.getSyncStatus.mock.calls.length).toBeGreaterThanOrEqual(2))
    expect(api.listCreatorMetrics.mock.calls.length).toBeGreaterThan(firstLoadCount)
  })

  it('refreshes the visible affiliate data every 30 seconds', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-08-18&to=2026-08-24&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.listCreatorMetrics).toHaveBeenCalled())
    const firstLoadCount = api.listCreatorMetrics.mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(30_000))
    await act(async () => vi.advanceTimersByTimeAsync(1))

    await waitFor(() => expect(api.listCreatorMetrics.mock.calls.length).toBeGreaterThan(firstLoadCount))
  })

  it('keeps independent URL-backed date ranges for creator and video tabs', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter
        initialEntries={[
          '/affiliate-center/videos?shopId=shop-1&currency=USD&creatorFrom=2026-07-01&creatorTo=2026-07-31&videoFrom=2026-08-01&videoTo=2026-08-07',
        ]}
      >
        <Routes>
          <Route
            element={
              <>
                <LocationProbe />
                <AffiliateCenterPage />
              </>
            }
            path="/affiliate-center/:resource"
          />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(api.listVideos).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-01',
        to: '2026-08-07',
        currency: 'USD',
        page: 1,
        pageSize: 50,
        sort: 'gmvMinor',
        order: 'desc',
      }),
    )
    expect(screen.getByRole('tab', { name: '所有视频' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('店铺')).toBeInTheDocument()
    expect(screen.getAllByLabelText('统计日期（非发布时间）')).toHaveLength(2)
    expect(screen.getByLabelText('币种')).toBeInTheDocument()
    expect(screen.queryByText('数据完整性')).not.toBeInTheDocument()
    await user.click(screen.getAllByLabelText('统计日期（非发布时间）')[0])
    expect(await screen.findByText('最近 7 天')).toBeInTheDocument()
    expect(screen.getByText('最近 30 天')).toBeInTheDocument()
    expect(screen.getByText('近两个月')).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: '达人' }))

    await waitFor(() =>
      expect(screen.getByLabelText('当前地址')).toHaveTextContent(
        '/affiliate-center/creators?shopId=shop-1&currency=USD&creatorFrom=2026-07-01&creatorTo=2026-07-31&videoFrom=2026-08-01&videoTo=2026-08-07',
      ),
    )
    await waitFor(() =>
      expect(api.listCreatorMetrics).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-07-01',
        to: '2026-07-31',
        currency: 'USD',
        page: 1,
        pageSize: 50,
        sort: 'affiliateGmvMinor',
        order: 'desc',
      }),
    )
    expect(screen.getByRole('tab', { name: '达人' })).toHaveAttribute('aria-selected', 'true')

    await user.click(screen.getByRole('tab', { name: '所有视频' }))
    await waitFor(() =>
      expect(screen.getByLabelText('当前地址')).toHaveTextContent(
        '/affiliate-center/videos?shopId=shop-1&currency=USD&creatorFrom=2026-07-01&creatorTo=2026-07-31&videoFrom=2026-08-01&videoTo=2026-08-07',
      ),
    )
  })

  it('does not clamp creator dates with the stale video availability during a tab switch', async () => {
    api.getSyncStatus.mockResolvedValue({
      items: [],
      browser: {
        ...onlineBrowser,
        latestAvailableDates: { creators: '2026-08-30', videos: '2026-08-29' },
      },
    })
    api.listCreatorMetrics.mockResolvedValue({ report: { status: 'complete' }, items: [], total: 0 })
    api.listVideos.mockResolvedValue({ run: { status: 'succeeded' }, items: [], total: 0 })
    const user = userEvent.setup()
    render(
      <MemoryRouter
        initialEntries={[
          '/affiliate-center/videos?shopId=shop-1&currency=USD&creatorFrom=2026-08-24&creatorTo=2026-08-30&videoFrom=2026-08-23&videoTo=2026-08-29',
        ]}
      >
        <Routes>
          <Route
            element={
              <>
                <LocationProbe />
                <AffiliateCenterPage />
              </>
            }
            path="/affiliate-center/:resource"
          />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.listVideos).toHaveBeenCalled())
    await user.click(screen.getByRole('tab', { name: '达人' }))

    await waitFor(() =>
      expect(screen.getByLabelText('当前地址')).toHaveTextContent('creatorFrom=2026-08-24&creatorTo=2026-08-30'),
    )
  })

  it('shows a real-data error without rendering mock fallback data', async () => {
    api.listVideos.mockRejectedValue(new Error('real API failed'))
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&from=2026-08-01&to=2026-08-07&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText(/所有视频真实数据读取失败。未回退到 Mock/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument()
  })

  it('keeps the last complete creator snapshot visible when a background refresh fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    api.listCreatorMetrics
      .mockResolvedValueOnce({
        report: { status: 'complete' },
        items: [],
        total: 1_234,
        summary: {
          creatorCount: 1_234,
          affiliateGmvMinor: 0,
          estimatedCommissionMinor: 0,
          itemsSold: 0,
          affiliateOrderCount: 0,
          productImpressions: 0,
        },
      })
      .mockRejectedValue(new Error('slow refresh'))
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/creators?shopId=shop-1&from=2026-07-05&to=2026-09-02&currency=USD']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('1,234')).toBeInTheDocument()
    await act(async () => vi.advanceTimersByTimeAsync(60_000))
    await act(async () => vi.advanceTimersByTimeAsync(1))

    expect(await screen.findByText(/Mock/)).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
  })
})
