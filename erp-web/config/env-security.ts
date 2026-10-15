const serverOnlyViteEnv =
  /^VITE_(?:DATABASE_URL|[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PRIVATE_KEY|ENCRYPTION_KEY|API_KEY))$/i

export function assertPublicViteEnv(env: Record<string, string>, mode?: string): void {
  const forbiddenNames = Object.keys(env)
    .filter((name) => serverOnlyViteEnv.test(name))
    .sort()
  if (forbiddenNames.length > 0) {
    throw new Error(`Server-only environment variables must not use VITE_: ${forbiddenNames.join(', ')}`)
  }

  if (mode === 'production') {
    for (const name of [
      'VITE_USE_MOCK', 'VITE_AUTH_USE_MOCK', 'VITE_DASHBOARD_USE_MOCK',
      'VITE_INVENTORY_USE_MOCK', 'VITE_ORDERS_USE_MOCK', 'VITE_PRODUCTS_USE_MOCK',
    ]) {
      if (env[name] !== 'false') throw new Error(`${name} must be explicitly false in production`)
    }
  }

  if (mode === 'production' && env.VITE_BESTSELLERS_USE_MOCK && env.VITE_BESTSELLERS_USE_MOCK !== 'false') {
    throw new Error('VITE_BESTSELLERS_USE_MOCK must be false in production')
  }
}
