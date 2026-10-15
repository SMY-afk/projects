import { describe, expect, it } from 'vitest'
import { parseDataRolloutConfig, shopIsInDataRollout } from './data-rollout'

const shop = (platformShopId: string) => ({ platformShopId })

describe('data rollout', () => {
  it('supports placeholder rollback and the three rollout stages', () => {
    expect(parseDataRolloutConfig({ stage: 'placeholder' }).stage).toBe('placeholder')
    expect(shopIsInDataRollout(shop('test-1'), parseDataRolloutConfig({ stage: 'test', testShopIds: 'test-1' }))).toBe(
      true,
    )
    expect(
      shopIsInDataRollout(shop('prod-1'), parseDataRolloutConfig({ stage: 'single', productionShopId: 'prod-1' })),
    ).toBe(true)
    expect(shopIsInDataRollout(shop('other'), parseDataRolloutConfig({ stage: 'all' }))).toBe(true)
  })

  it('fails closed when a staged shop allowlist is missing', () => {
    expect(parseDataRolloutConfig({}).stage).toBe('placeholder')
    expect(parseDataRolloutConfig({ stage: 'invalid' }).stage).toBe('placeholder')
    expect(shopIsInDataRollout(shop('test-1'), parseDataRolloutConfig({ stage: 'test' }))).toBe(false)
    expect(shopIsInDataRollout(shop('prod-1'), parseDataRolloutConfig({ stage: 'single' }))).toBe(false)
  })
})
