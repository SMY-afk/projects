import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { dashboardApi } from '../api/dashboard.api'
import type { DashboardQueryParams, DashboardRankingDays } from '../types/dashboard.types'

export const dashboardQueryKeys = {
  all: ['dashboard'] as const,
  snapshot: (params: DashboardQueryParams) => ['dashboard', 'snapshot', params] as const,
  affiliateRankings: (params: DashboardQueryParams, days: DashboardRankingDays) =>
    ['dashboard', 'affiliate-rankings', params.platform, params.site, params.shopId, params.currency, days] as const,
}

export const useDashboardSnapshotQuery = (params: DashboardQueryParams) =>
  useQuery({
    queryKey: dashboardQueryKeys.snapshot(params),
    queryFn: () => dashboardApi.getSnapshot(params),
    placeholderData: keepPreviousData,
  })

export const useDashboardAffiliateRankingsQuery = (params: DashboardQueryParams, days: DashboardRankingDays) =>
  useQuery({
    queryKey: dashboardQueryKeys.affiliateRankings(params, days),
    queryFn: () => dashboardApi.getAffiliateRankings(params, days),
    placeholderData: keepPreviousData,
  })
