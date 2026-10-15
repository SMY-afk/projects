import { afterEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => vi.fn())
const downloadFileMock = vi.hoisted(() => vi.fn())

vi.mock('@/services/http-client', () => ({ downloadFile: downloadFileMock, request: requestMock }))

async function loadApi() {
  vi.resetModules()
  return import('./affiliate-center.api')
}

describe('Affiliate Center API', () => {
  afterEach(() => {
    requestMock.mockReset()
    downloadFileMock.mockReset()
  })

  it('loads the frozen resource contract', async () => {
    requestMock.mockResolvedValue({ items: [] })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.listResources()

    expect(requestMock).toHaveBeenCalledWith({
      method: 'get',
      url: '/affiliate-center/resources',
    })
  })

  it('binds report and creator reads to the selected shop', async () => {
    requestMock.mockResolvedValue({ items: [] })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.listReports('shop-1')
    await affiliateCenterApi.listCreators('shop-1', 'report-1', 2, 25)

    expect(requestMock).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/affiliate-center/reports',
      params: { shopId: 'shop-1' },
    })
    expect(requestMock).toHaveBeenNthCalledWith(2, {
      method: 'get',
      url: '/affiliate-center/reports/report-1/creators',
      params: { shopId: 'shop-1', page: 2, pageSize: 25 },
    })
  })

  it('uses the stable creator, video, status, and sync contracts', async () => {
    requestMock.mockResolvedValue({ items: [] })
    const { affiliateCenterApi } = await loadApi()
    const query = {
      shopId: 'shop-1',
      from: '2026-08-01',
      to: '2026-08-07',
      currency: 'USD',
      page: 2,
      pageSize: 25,
    }

    await affiliateCenterApi.listCreatorMetrics({ ...query, sort: 'affiliateGmvMinor' })
    await affiliateCenterApi.listVideos({ ...query, sort: 'views', creatorOpenId: 'open-1' })
    await affiliateCenterApi.getSyncStatus('shop-1')
    await affiliateCenterApi.sync({
      shopId: 'shop-1',
      from: '2026-08-01',
      to: '2026-08-07',
      currency: 'USD',
      resources: ['creators', 'videos'],
    })

    expect(requestMock).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/affiliate-center/creators',
      params: { ...query, sort: 'affiliateGmvMinor' },
      timeout: 60_000,
    })
    expect(requestMock).toHaveBeenNthCalledWith(2, {
      method: 'get',
      url: '/affiliate-center/videos',
      params: { ...query, sort: 'views', creatorOpenId: 'open-1' },
      timeout: 60_000,
    })
    expect(requestMock).toHaveBeenNthCalledWith(3, {
      method: 'get',
      url: '/affiliate-center/sync-status',
      params: { shopId: 'shop-1' },
    })
    expect(requestMock).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/affiliate-center/sync',
      data: {
        shopId: 'shop-1',
        from: '2026-08-01',
        to: '2026-08-07',
        currency: 'USD',
        resources: ['creators', 'videos'],
      },
    })
  })

  it('loads affiliate live accounts from the dedicated affiliate endpoint', async () => {
    requestMock.mockResolvedValue({ data: [] })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.listLiveAccounts({
      shopId: 'shop-1',
      page: 2,
      pageSize: 50,
      preset: 'last7d',
      sortBy: 'gmv',
      sortOrder: 'desc',
    })

    expect(requestMock).toHaveBeenCalledWith({
      method: 'get',
      url: '/affiliate-center/live-accounts',
      params: {
        shopId: 'shop-1',
        page: 2,
        pageSize: 50,
        preset: 'last7d',
        sortBy: 'gmv',
        sortOrder: 'desc',
      },
    })
  })

  it('downloads the local five-shop export with an extended timeout', async () => {
    downloadFileMock.mockResolvedValue({ blob: new Blob() })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.exportLocal('2026-07-03', '2026-09-03')

    expect(downloadFileMock).toHaveBeenCalledWith('/affiliate-center/local-export', {
      method: 'get',
      params: { from: '2026-07-03', to: '2026-09-03' },
      timeout: 120_000,
    })
  })

  it('downloads the fixed two-table Feishu export with an extended timeout', async () => {
    downloadFileMock.mockResolvedValue({ blob: new Blob() })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.exportFeishu()

    expect(downloadFileMock).toHaveBeenCalledWith('/affiliate-center/feishu-export', {
      method: 'get',
      timeout: 300_000,
    })
  })

  it('requests the latest affiliate live-account data for the selected range', async () => {
    requestMock.mockResolvedValue({ items: [], captureMode: 'official_api_owned' })
    const { affiliateCenterApi } = await loadApi()

    await affiliateCenterApi.syncLiveAccounts({ shopId: 'shop-1', preset: 'last60d' })

    expect(requestMock).toHaveBeenCalledWith({
      method: 'post',
      url: '/affiliate-center/live-accounts/sync',
      data: { shopId: 'shop-1', preset: 'last60d' },
    })
  })

  it('passes custom live dates through the dedicated endpoint', async () => {
    requestMock.mockResolvedValue({ data: [] })
    const { affiliateCenterApi } = await loadApi()
    const params = {
      shopId: 'shop-1',
      page: 1,
      pageSize: 50,
      preset: 'custom' as const,
      customFrom: '2026-08-01',
      customTo: '2026-08-15',
    }
    const syncParams = {
      shopId: params.shopId,
      preset: params.preset,
      customFrom: params.customFrom,
      customTo: params.customTo,
    }

    await affiliateCenterApi.listLiveAccounts(params)
    await affiliateCenterApi.syncLiveAccounts(syncParams)

    expect(requestMock).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/affiliate-center/live-accounts',
      params,
    })
    expect(requestMock).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/affiliate-center/live-accounts/sync',
      data: syncParams,
    })
  })
})
