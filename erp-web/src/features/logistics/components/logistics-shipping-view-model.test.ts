import { describe, expect, it } from 'vitest'
import type { LogisticsPackage, LogisticsShippingQuote, LogisticsTaskItem } from '../types/logistics.types'
import {
  formatDeliveryEstimate,
  formatShippingFee,
  resolveDispatchLines,
  shippingQuoteKey,
} from './logistics-shipping-view-model'

const quote: LogisticsShippingQuote = {
  carrierId: 'carrier-1',
  carrierName: 'DHL',
  serviceId: 'service-1',
  serviceName: 'Express',
  accountId: null,
  amountMinor: 1234,
  currency: 'USD',
  estimatedDaysMin: 2,
  estimatedDaysMax: 4,
  quoteType: 'calculated',
  warnings: [],
}

describe('logistics shipping view model', () => {
  it('formats carrier quote fee, delivery estimate and stable selection key', () => {
    expect(formatShippingFee(quote)).toBe('USD 12.34')
    expect(formatDeliveryEstimate(quote)).toBe('2-4 天')
    expect(shippingQuoteKey(quote)).toBe('carrier-1:service-1:')
    expect(formatShippingFee({ ...quote, amountMinor: null })).toBe('人工询价')
  })

  it('resolves package items to SKU rows for dispatch confirmation', () => {
    const packageItem = {
      id: 'package-1',
      packageNumber: 'PKG-001',
      items: [{ id: 'package-item-1', taskItemId: 'task-item-1', quantity: 2 }],
    } as LogisticsPackage
    const taskItems = [
      {
        id: 'task-item-1',
        sellerSku: 'SKU-RED',
        platformSkuId: 'platform-sku-1',
        productName: '积木套装',
        skuName: '红色',
      } as LogisticsTaskItem,
    ]

    expect(resolveDispatchLines(packageItem, taskItems)).toEqual([
      {
        id: 'task-item-1',
        sku: 'SKU-RED',
        productName: '积木套装',
        specification: '红色',
        quantity: 2,
      },
    ])
  })
})
