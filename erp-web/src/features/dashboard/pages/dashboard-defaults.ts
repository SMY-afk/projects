import type { DashboardQueryParams } from '../types/dashboard.types'

export const defaultDashboardParams = (): DashboardQueryParams => ({
  currency: 'USD',
  timezone: 'America/Los_Angeles',
  realtimeRange: 'today',
  trendRange: 'last7d',
  orderRange: 'last7d',
})
