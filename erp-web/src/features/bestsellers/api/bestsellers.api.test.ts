import { afterEach, describe, expect, it, vi } from 'vitest'

const requestMock = vi.hoisted(() => vi.fn())

vi.mock('@/services/http-client', () => ({ request: requestMock }))

async function loadApi() {
  vi.resetModules()
  return import('./bestsellers.api')
}

describe('Bestsellers API', () => {
  afterEach(() => {
    requestMock.mockReset()
    vi.unstubAllEnvs()
  })

  it('uses HTTP unless the dedicated Bestsellers Mock flag is true', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_BESTSELLERS_USE_MOCK', 'false')
    requestMock.mockResolvedValue([])
    const { bestsellersApi, isBestsellersMock } = await loadApi()

    await bestsellersApi.listShops()

    expect(isBestsellersMock).toBe(false)
    expect(requestMock).toHaveBeenCalledWith({ method: 'get', url: '/shops' })
  })

  it('surfaces real-mode failures without returning Mock ranking data', async () => {
    vi.stubEnv('VITE_BESTSELLERS_USE_MOCK', 'false')
    const failure = new Error('backend unavailable')
    requestMock.mockRejectedValue(failure)
    const { bestsellersApi, isBestsellersMock } = await loadApi()

    await expect(
      bestsellersApi.list('products', {
        shopId: 'shop-1',
        date: '2026-08-19',
        timeSlot: '7D',
        currency: 'USD',
      }),
    ).rejects.toBe(failure)
    expect(isBestsellersMock).toBe(false)
    expect(requestMock).toHaveBeenCalledTimes(1)
  })

  it('sends the exact authorization, ranking and sync contracts', async () => {
    vi.stubEnv('VITE_BESTSELLERS_USE_MOCK', 'false')
    requestMock.mockResolvedValue({})
    const { bestsellersApi } = await loadApi()
    const query = {
      shopId: 'shop-1',
      date: '2026-08-19',
      timeSlot: '7D' as const,
      currency: 'USD' as const,
      authorType: 'AFFILIATE' as const,
    }

    await bestsellersApi.authorizationStatus('shop-1')
    await bestsellersApi.reauthorizationUrl('shop-1')
    await bestsellersApi.list('creators', query)
    await bestsellersApi.sync({ ...query, entityTypes: ['creators'] })

    expect(requestMock).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/bestsellers/authorization-status',
      params: { shopId: 'shop-1' },
    })
    expect(requestMock).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/v1/shops/tiktok/shop-1/reauthorization-url',
    })
    expect(requestMock).toHaveBeenNthCalledWith(3, {
      method: 'get',
      url: '/bestsellers/creators',
      params: query,
    })
    expect(requestMock).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/bestsellers/sync',
      data: { ...query, entityTypes: ['creators'] },
    })
  })

  it('uses local four-entity fixtures only when explicitly enabled', async () => {
    vi.stubEnv('VITE_BESTSELLERS_USE_MOCK', 'true')
    const { bestsellersApi, isBestsellersMock } = await loadApi()

    const results = await Promise.all(
      (['products', 'creators', 'videos', 'lives'] as const).map((entity) =>
        bestsellersApi.list(entity, {
          shopId: 'bestsellers-mock-shop',
          date: '2026-08-19',
          timeSlot: '7D',
          currency: 'USD',
          authorType: entity === 'creators' ? 'ALL' : undefined,
        }),
      ),
    )

    expect(isBestsellersMock).toBe(true)
    expect(results.every((result) => result.data.items.length > 0)).toBe(true)
    expect(requestMock).not.toHaveBeenCalled()
  })
})
