import { describe, expect, it } from 'vitest'
import { dashboardProductRowKey } from './dashboard-row-key'
import type { DashboardProductPerformance } from '../types/dashboard.types'

const row: DashboardProductPerformance = {
  name: 'Red car',
  sku: 'SKU-1',
  productId: 'product-1',
  platform: 'tiktok',
  store: 'store-1',
  salesVolume: 1,
  salesAmountMinor: 100,
  netSalesAmountMinor: 90,
}

describe('dashboard product row key', () => {
  it('distinguishes rows split by product name and platform', () => {
    expect(dashboardProductRowKey(row)).not.toBe(dashboardProductRowKey({ ...row, name: 'Blue car' }))
    expect(dashboardProductRowKey(row)).not.toBe(dashboardProductRowKey({ ...row, platform: 'amazon' }))
  })
})
