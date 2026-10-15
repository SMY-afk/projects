import { expect, it } from 'vitest'
import { shippingMethodLabel } from './logistics-shipping-method'

it('shows the official shipping method without substituting unknown values', () => {
  expect(shippingMethodLabel('SELLER')).toBe('商家物流')
  expect(shippingMethodLabel('TIKTOK', 'FULFILLMENT_BY_SELLER')).toBe('TikTok物流')
  expect(shippingMethodLabel('TIKTOK', 'FULFILLMENT_BY_TIKTOK')).toBe('FBT物流')
  expect(shippingMethodLabel('TIKTOK')).toBe('平台物流（具体类型待确认）')
  expect(shippingMethodLabel(null)).toBe('暂未获取')
  expect(shippingMethodLabel('OTHER')).toBe('OTHER')
})
