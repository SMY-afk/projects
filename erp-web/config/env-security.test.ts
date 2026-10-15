import { describe, expect, it } from 'vitest'
import { assertPublicViteEnv } from './env-security'

const productionEnv = {
  VITE_USE_MOCK: 'false', VITE_AUTH_USE_MOCK: 'false', VITE_DASHBOARD_USE_MOCK: 'false',
  VITE_INVENTORY_USE_MOCK: 'false', VITE_ORDERS_USE_MOCK: 'false', VITE_PRODUCTS_USE_MOCK: 'false',
}

describe('Vite environment security', () => {
  it('allows public browser configuration', () => {
    expect(() =>
      assertPublicViteEnv({
        VITE_API_BASE_URL: '/api',
        VITE_API_CONTRACT_VERSION: 'v1',
        VITE_USE_MOCK: 'false',
      }),
    ).not.toThrow()
  })

  it.each([
    'VITE_TIKTOK_APP_SECRET',
    'VITE_TOKEN_ENCRYPTION_KEY',
    'VITE_POSTGRES_PASSWORD',
    'VITE_DATABASE_URL',
    'VITE_JWT_SECRET',
  ])('rejects the server-only variable %s', (name) => {
    expect(() => assertPublicViteEnv({ [name]: 'sensitive-value' })).toThrow(name)
  })

  it('rejects Bestsellers Mock in production', () => {
    expect(() => assertPublicViteEnv({ ...productionEnv, VITE_BESTSELLERS_USE_MOCK: 'true' }, 'production')).toThrow(
      'VITE_BESTSELLERS_USE_MOCK must be false in production',
    )
    expect(() => assertPublicViteEnv({ ...productionEnv, VITE_BESTSELLERS_USE_MOCK: 'false' }, 'production')).not.toThrow()
  })

  it.each(Object.keys(productionEnv))('rejects missing or enabled production switch %s', (key) => {
    expect(() => assertPublicViteEnv({ ...productionEnv, [key]: '' }, 'production')).toThrow(key)
    expect(() => assertPublicViteEnv({ ...productionEnv, [key]: 'true' }, 'production')).toThrow(key)
  })
})
