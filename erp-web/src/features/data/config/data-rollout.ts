export type DataRolloutStage = 'placeholder' | 'test' | 'single' | 'all'

export interface DataRolloutConfig {
  stage: DataRolloutStage
  testShopIds: Set<string>
  productionShopId?: string
}

interface DataRolloutSource {
  stage?: string
  testShopIds?: string
  productionShopId?: string
}

const stages = new Set<DataRolloutStage>(['placeholder', 'test', 'single', 'all'])

export function parseDataRolloutConfig(source: DataRolloutSource): DataRolloutConfig {
  const stage = stages.has(source.stage as DataRolloutStage) ? (source.stage as DataRolloutStage) : 'placeholder'
  return {
    stage,
    testShopIds: new Set(
      (source.testShopIds ?? '')
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
    ),
    productionShopId: source.productionShopId?.trim() || undefined,
  }
}

export function shopIsInDataRollout(shop: { platformShopId: string }, config: DataRolloutConfig): boolean {
  if (config.stage === 'all') return true
  if (config.stage === 'test') return config.testShopIds.has(shop.platformShopId)
  if (config.stage === 'single') return shop.platformShopId === config.productionShopId
  return false
}

const runtimeEnv = import.meta.env as unknown as Record<string, unknown>
const envString = (key: string) => (typeof runtimeEnv[key] === 'string' ? runtimeEnv[key] : undefined)

export const dataRolloutConfig = parseDataRolloutConfig({
  stage: envString('VITE_DATA_ROLLOUT_STAGE'),
  testShopIds: envString('VITE_DATA_TEST_SHOP_IDS'),
  productionShopId: envString('VITE_DATA_PRODUCTION_SHOP_ID'),
})
