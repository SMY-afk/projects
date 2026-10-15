import { describe, expect, it } from 'vitest'
import { formatCurrentPrice } from './product-price'
import type { Product } from '../types/product.types'

const product = (overrides: Partial<Product> = {}): Product => ({
  id: 'product-1',
  shopId: 'shop-1',
  name: 'Toy',
  code: 'TOY-1',
  status: 'ACTIVATE',
  updatedAt: '2026-08-12 12:00',
  owner: 'Shop',
  shopName: 'Shop',
  category: 'Toy',
  stock: 2,
  skus: [],
  ...overrides,
})

describe('formatCurrentPrice', () => {
  it('uses the API product price when available', () => {
    expect(formatCurrentPrice(product({ currentPrice: 'USD 19.99' }))).toBe('USD 19.99')
  })

  it('derives a price range from SKU prices', () => {
    expect(
      formatCurrentPrice(
        product({
          skus: [
            { id: '1', platformSkuId: '1', sellerSku: 'A', stock: 1, priceMinor: 6800, currency: 'USD' },
            { id: '2', platformSkuId: '2', sellerSku: 'B', stock: 1, priceMinor: 20800, currency: 'USD' },
          ],
        }),
      ),
    ).toBe('USD 68.00 - 208.00')
  })

  it('returns null when TikTok has no price', () => {
    expect(formatCurrentPrice(product())).toBeNull()
  })
})
