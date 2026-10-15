import type { LogisticsOrderCategory } from '../utils/logistics-order-categories'

export type LogisticsOrderAlert = 'unshipped_48h' | 'uncollected_48h' | 'undelivered_77h'
export type LogisticsAlertPhase = 'upcoming' | 'overdue'
export interface LogisticsWarnings {
  cards: { key: LogisticsOrderAlert; thresholdHours: number; upcomingCount: number; overdueCount: number; closestRemainingSeconds: number; longestOverdueSeconds: number }[]
  uniqueOrderCount: number
  upcomingUniqueOrderCount: number
  overdueUniqueOrderCount: number
  leadHours: number
  asOf: string
  lastDataSyncAt: string | null
}

export interface LogisticsStatusPackage {
  packageId: string
  packageStatus: string
  carrierName: string | null
  trackingNumberMasked: string | null
  trackingStatus?: string | null
  trackingCheckedAt?: string | null
}

export interface LogisticsStatusOrder {
  id: string
  shopId: string
  shopName: string
  orderNumber: string
  orderCreatedAt: string
  platformStatus: string
  shippingType?: string | null
  fulfillmentType?: string | null
  platformUpdatedAt: string
  erpSyncedAt: string
  deliveredAt?: string | null
  officialCheckedAt?: string | null
  officialTrackingStatus?: string | null
  packages: LogisticsStatusPackage[]
  alerts?: Partial<Record<LogisticsOrderAlert, number>>
}

export interface LogisticsStatusList {
  items: LogisticsStatusOrder[]
  total: number
  page: number
  pageSize: number
  categoryCounts?: Partial<Record<LogisticsOrderCategory, number>>
  syncResults?: { shopId: string; status: string; syncedAt: string | null }[]
  refreshFailedCount?: number
  warnings?: LogisticsWarnings | null
}

export interface LogisticsStatusLive {
  orderId: string
  trackingStatus: string | null
  checkedAt: string
  erpSyncedAt?: string | null
  events: { status: string; occurredAt: string; description: string | null; actionCode: string }[]
  packages: LogisticsStatusPackage[]
  platformStatus: string
  shippingType?: string | null
  fulfillmentType?: string | null
  platformUpdatedAt: string
  orderCreatedAt: string
  shippedAt: string | null
  firstLocationAt: string | null
  deliveredAt: string | null
  shippedDescription: string | null
  firstLocationDescription: string | null
  deliveredDescription: string | null
  milestoneNotes: string[]
}
