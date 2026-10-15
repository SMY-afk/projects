export const isMockEnabled = import.meta.env.VITE_USE_MOCK !== 'false'

type FeatureApiModule = 'auth' | 'dashboard' | 'inventory' | 'orders' | 'products'

const featureMockEnvKeys: Record<FeatureApiModule, string> = {
  auth: 'VITE_AUTH_USE_MOCK',
  dashboard: 'VITE_DASHBOARD_USE_MOCK',
  inventory: 'VITE_INVENTORY_USE_MOCK',
  orders: 'VITE_ORDERS_USE_MOCK',
  products: 'VITE_PRODUCTS_USE_MOCK',
}

export function isFeatureMockEnabled(module: FeatureApiModule): boolean {
  if (isMockEnabled) return true
  return import.meta.env[featureMockEnvKeys[module]] !== 'false'
}

/** Data Mock is opt-in so real-mode failures can never fall back to mock values. */
export const isDataMockEnabled = () => import.meta.env.VITE_DATA_USE_MOCK === 'true'

/** Bestsellers Mock is opt-in so real-mode failures remain visible. */
export const isBestsellersMockEnabled = () => import.meta.env.VITE_BESTSELLERS_USE_MOCK === 'true'

/** Finance Mock is opt-in so settlement failures and discrepancies stay visible. */
export const isFinanceMockEnabled = () => import.meta.env.VITE_FINANCE_USE_MOCK === 'true'
