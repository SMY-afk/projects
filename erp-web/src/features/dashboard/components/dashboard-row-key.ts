import type { DashboardProductPerformance } from '../types/dashboard.types'

export function dashboardProductRowKey(row: DashboardProductPerformance): string {
  return JSON.stringify([row.productId, row.sku, row.platform, row.store, row.name])
}
