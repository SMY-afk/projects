import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadApiMode() {
  vi.resetModules()
  return import('./api-mode')
}

describe('feature API mode', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('keeps every feature on Mock while the global Mock switch is enabled', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_PRODUCTS_USE_MOCK', 'false')

    const { isFeatureMockEnabled } = await loadApiMode()

    expect(isFeatureMockEnabled('products')).toBe(true)
  })

  it('switches products to HTTP while orders remain on Mock', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false')
    vi.stubEnv('VITE_AUTH_USE_MOCK', 'true')
    vi.stubEnv('VITE_PRODUCTS_USE_MOCK', 'false')
    vi.stubEnv('VITE_ORDERS_USE_MOCK', 'true')

    const { isFeatureMockEnabled } = await loadApiMode()

    expect(isFeatureMockEnabled('auth')).toBe(true)
    expect(isFeatureMockEnabled('products')).toBe(false)
    expect(isFeatureMockEnabled('orders')).toBe(true)
  })

  it('keeps an unspecified feature on Mock during staged rollout', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'false')
    vi.stubEnv('VITE_DASHBOARD_USE_MOCK', undefined)

    const { isFeatureMockEnabled } = await loadApiMode()

    expect(isFeatureMockEnabled('dashboard')).toBe(true)
  })

  it('requires the dedicated switch to enable Data Mock', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_DATA_USE_MOCK', 'false')
    let apiMode = await loadApiMode()
    expect(apiMode.isDataMockEnabled()).toBe(false)

    vi.stubEnv('VITE_DATA_USE_MOCK', 'true')
    apiMode = await loadApiMode()
    expect(apiMode.isDataMockEnabled()).toBe(true)
  })

  it('requires the dedicated switch to enable Finance Mock', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'false')
    let apiMode = await loadApiMode()
    expect(apiMode.isFinanceMockEnabled()).toBe(false)

    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'true')
    apiMode = await loadApiMode()
    expect(apiMode.isFinanceMockEnabled()).toBe(true)
  })
})
