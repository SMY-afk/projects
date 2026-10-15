import { describe, expect, it } from 'vitest'
import { parseBestsellerRolloutConfig, shopIsInBestsellerRollout } from './bestseller-rollout'

const shop = (platformShopId: string) => ({ platformShopId })

describe('Bestseller rollout', () => {
  it('starts with one stable platform shop and can later open all shops', () => {
    const single = parseBestsellerRolloutConfig({ stage: 'single', productionShopId: 'shop-1' })

    expect(shopIsInBestsellerRollout(shop('shop-1'), single)).toBe(true)
    expect(shopIsInBestsellerRollout(shop('shop-2'), single)).toBe(false)
    expect(shopIsInBestsellerRollout(shop('shop-2'), parseBestsellerRolloutConfig({ stage: 'all' }))).toBe(true)
  })

  it('fails closed when the single-shop target is missing or the stage is invalid', () => {
    expect(shopIsInBestsellerRollout(shop('shop-1'), parseBestsellerRolloutConfig({ stage: 'single' }))).toBe(false)
    expect(shopIsInBestsellerRollout(shop('shop-1'), parseBestsellerRolloutConfig({ stage: 'invalid' }))).toBe(false)
  })
})
