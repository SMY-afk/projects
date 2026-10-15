import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
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

vi.mock('../api/affiliate-center.api', () => ({ affiliateCenterApi: api }))

function SwitchShopButton() {
  const navigate = useNavigate()
  return (
    <button
      onClick={() =>
        void navigate('/affiliate-center/videos?shopId=shop-2&currency=USD&videoFrom=2026-08-02&videoTo=2026-08-31')
      }
    >
      switch-shop
    </button>
  )
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, reject, resolve }
}

describe('AffiliateCenterPage shop switching', () => {
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
    api.listResources.mockResolvedValue({
      items: [],
      queryDimensions: [],
      display: { creators: { metrics: [] }, videos: { metrics: [] } },
    })
    api.listShops.mockResolvedValue([
      { id: 'shop-1', shopName: 'Akeleo Toys', currency: 'USD' },
      { id: 'shop-2', shopName: 'NEOPUP', currency: 'USD' },
    ])
    api.listCreatorMetrics.mockResolvedValue({ report: null, items: [], total: 0 })
    api.listVideos.mockImplementation(({ shopId }: { shopId: string }) =>
      Promise.resolve(
        shopId === 'shop-1'
          ? {
              run: null,
              items: [],
              total: 0,
              summary: { videoCount: 0, gmvMinor: 0, orderCount: 0 },
            }
          : {
              run: { runId: 'shop-2-complete', status: 'succeeded' },
              items: [],
              total: 0,
              summary: { videoCount: 177, gmvMinor: 148_173, orderCount: 23 },
            },
      ),
    )
    api.getSyncStatus.mockResolvedValue({
      items: [],
      browser: {
        state: 'online',
        cdpAvailable: true,
        sessionAvailable: true,
        updatedAt: '2026-09-03T03:00:00Z',
        recoveredAt: null,
        latestAvailableDates: { videos: '2026-08-31' },
      },
    })
  })

  it('does not show an old shop sync failure after switching shops', async () => {
    const pendingSync = deferred<never>()
    api.sync.mockReturnValueOnce(pendingSync.promise)
    const user = userEvent.setup()
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&currency=USD&videoFrom=2026-08-02&videoTo=2026-08-31']}
      >
        <SwitchShopButton />
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.sync).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: 'switch-shop' }))
    await waitFor(() => expect(api.listVideos).toHaveBeenCalledWith(expect.objectContaining({ shopId: 'shop-2' })))

    await act(async () => {
      pendingSync.reject(new HttpError('Request failed.', { kind: 'network' }))
      await Promise.resolve()
    })

    expect(screen.queryByText(/Request failed/)).not.toBeInTheDocument()
    expect(screen.getByText('$1,481.73')).toBeInTheDocument()
  })

  it('does not present an incomplete snapshot as real zero-value data', async () => {
    api.sync.mockResolvedValue({ items: [], captureMode: 'browser_daemon_owned' })
    render(
      <MemoryRouter
        initialEntries={['/affiliate-center/videos?shopId=shop-1&currency=USD&videoFrom=2026-08-02&videoTo=2026-08-31']}
      >
        <Routes>
          <Route element={<AffiliateCenterPage />} path="/affiliate-center/:resource" />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(api.sync).toHaveBeenCalledTimes(1))

    expect(screen.queryByText('$0.00')).not.toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
})
