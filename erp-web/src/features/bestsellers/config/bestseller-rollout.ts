export type BestsellerRolloutStage = 'single' | 'all'

export interface BestsellerRolloutConfig {
  stage: BestsellerRolloutStage
  productionShopId?: string
}

interface BestsellerRolloutSource {
  stage?: string
  productionShopId?: string
}

export function parseBestsellerRolloutConfig(source: BestsellerRolloutSource): BestsellerRolloutConfig {
  return {
    stage: source.stage === 'all' ? 'all' : 'single',
    productionShopId: source.productionShopId?.trim() || undefined,
  }
}

export function shopIsInBestsellerRollout(shop: { platformShopId: string }, config: BestsellerRolloutConfig): boolean {
  return config.stage === 'all' || shop.platformShopId === config.productionShopId
}

const runtimeEnv = import.meta.env as unknown as Record<string, unknown>
const envString = (key: string) => (typeof runtimeEnv[key] === 'string' ? runtimeEnv[key] : undefined)

export const bestsellerRolloutConfig = parseBestsellerRolloutConfig({
  stage: envString('VITE_BESTSELLERS_ROLLOUT_STAGE'),
  productionShopId: envString('VITE_BESTSELLERS_PRODUCTION_SHOP_ID'),
})
