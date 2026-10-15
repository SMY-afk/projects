import type { Product } from '../types/product.types'

export function formatCurrentPrice(product: Product) {
  if (product.currentPrice) return product.currentPrice
  const pricedSkus = product.skus.filter((sku) => sku.priceMinor > 0)
  if (!pricedSkus.length) return null
  const currencies = new Set(pricedSkus.map((sku) => sku.currency))
  if (currencies.size !== 1)
    return pricedSkus.map((sku) => `${sku.currency} ${(sku.priceMinor / 100).toFixed(2)}`).join(', ')
  const currency = pricedSkus[0].currency
  const prices = [...new Set(pricedSkus.map((sku) => sku.priceMinor))].sort((left, right) => left - right)
  const minimum = (prices[0] / 100).toFixed(2)
  const maximum = (prices[prices.length - 1] / 100).toFixed(2)
  return prices.length === 1 ? `${currency} ${minimum}` : `${currency} ${minimum} - ${maximum}`
}
