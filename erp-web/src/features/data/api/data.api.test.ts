import { afterEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => vi.fn())

vi.mock('@/services/http-client', () => ({ request: requestMock }))

async function loadDataApi() {
  vi.resetModules()
  return import('./data.api')
}

describe('data API mode', () => {
  afterEach(() => {
    requestMock.mockReset()
    vi.unstubAllEnvs()
  })

  it('uses HTTP in real mode even while the global Mock switch is on', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_DATA_USE_MOCK', 'false')
    requestMock.mockResolvedValue([])
    const { dataApi, isDataMock } = await loadDataApi()

    await dataApi.listShops()

    expect(isDataMock).toBe(false)
    expect(requestMock).toHaveBeenCalledWith({ method: 'get', url: '/shops' })
  })

  it('uses local fixtures only when the dedicated Data Mock switch is true', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false')
    vi.stubEnv('VITE_DATA_USE_MOCK', 'true')
    const { dataApi, isDataMock } = await loadDataApi()

    const shops = await dataApi.listShops()

    expect(isDataMock).toBe(true)
    expect(shops[0]?.id).toBe('data-mock-shop')
    expect(requestMock).not.toHaveBeenCalled()
  })

  it('sends the exact exclusive video window and resync payload', async () => {
    vi.stubEnv('VITE_DATA_USE_MOCK', 'false')
    requestMock.mockResolvedValue({ data: [] })
    const { dataApi } = await loadDataApi()
    const query = {
      shopId: 'shop-1',
      from: '2026-08-01T07:00:00.000Z',
      to: '2026-08-16T07:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }

    await dataApi.videos(query, { sortBy: 'gmv', sortOrder: 'desc' })
    await dataApi.resync({
      shopId: query.shopId,
      resourceTypes: ['video'],
      windowStart: query.from,
      windowEnd: query.to,
      currency: query.currency,
      accountType: query.accountType,
    })

    expect(requestMock).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/data/videos',
      params: { ...query, sortBy: 'gmv', sortOrder: 'desc' },
    })
    expect(requestMock).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/data/resync',
      data: {
        shopId: 'shop-1',
        resourceTypes: ['video'],
        windowStart: query.from,
        windowEnd: query.to,
        currency: 'USD',
        accountType: 'ALL',
      },
    })
  })

  it('keeps a real video request failure visible instead of falling back to Mock data', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_DATA_USE_MOCK', 'false')
    requestMock.mockRejectedValue(new Error('network failed'))
    const { dataApi, isDataMock } = await loadDataApi()
    const query = {
      shopId: 'shop-1',
      from: '2026-08-19T00:00:00.000Z',
      to: '2026-08-20T00:00:00.000Z',
      currency: 'USD' as const,
      accountType: 'ALL' as const,
    }

    await expect(dataApi.videos(query, { sortBy: 'gmv', sortOrder: 'desc' })).rejects.toThrow('network failed')

    expect(isDataMock).toBe(false)
    expect(requestMock).toHaveBeenCalledWith({
      method: 'get',
      url: '/data/videos',
      params: { ...query, sortBy: 'gmv', sortOrder: 'desc' },
    })
  })
})
