import { request } from '@/services/http-client'
import type {
  DashboardAffiliateRankings,
  DashboardQueryParams,
  DashboardRankingDays,
  DashboardSnapshot,
} from '../types/dashboard.types'

export interface DashboardApi {
  getSnapshot(params: DashboardQueryParams): Promise<DashboardSnapshot>
  getAffiliateRankings(params: DashboardQueryParams, days: DashboardRankingDays): Promise<DashboardAffiliateRankings>
}

export const dashboardApi: DashboardApi = {
  getSnapshot: (params) => request<DashboardSnapshot>({ method: 'get', url: '/dashboard/snapshot', params }),
  getAffiliateRankings: ({ platform, site, shopId, currency }, days) =>
    request<DashboardAffiliateRankings>({
      method: 'get',
      url: '/dashboard/affiliate-rankings',
      params: { platform, site, shopId, currency, days },
    }),
}
