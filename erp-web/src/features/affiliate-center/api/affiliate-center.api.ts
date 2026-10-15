import { downloadFile, request } from '@/services/http-client'
import type {
  AffiliateLiveAccountEnvelope,
  AffiliateLiveAccountQuery,
  AffiliateLiveAccountSyncRequest,
  AffiliateLiveAccountSyncResponse,
} from '../types/affiliate-live-account.types'
import type {
  AffiliateCreatorPage,
  AffiliateCreatorDetail,
  AffiliateCreatorDetailPage,
  AffiliateCreatorDetailResource,
  AffiliateCreatorListQuery,
  AffiliateCreatorReport,
  AffiliateResourceContract,
  AffiliateSyncStatusResponse,
  AffiliateShop,
  AffiliateStableCreatorPage,
  AffiliateStableQuery,
  AffiliateSyncRequest,
  AffiliateSyncIntentResponse,
  AffiliateVideoListQuery,
  AffiliateVideoPage,
} from '../types/affiliate-center.types'

export const affiliateCenterApi = {
  listResources() {
    return request<AffiliateResourceContract>({
      method: 'get',
      url: '/affiliate-center/resources',
    })
  },
  async listShops() {
    const result = await request<{ items: AffiliateShop[] }>({
      method: 'get',
      url: '/affiliate-center/shops',
    })
    return result.items
  },
  async listReports(shopId: string) {
    const result = await request<{ items: AffiliateCreatorReport[] }>({
      method: 'get',
      url: '/affiliate-center/reports',
      params: { shopId },
    })
    return result.items
  },
  listCreators(shopId: string, reportId: string, page = 1, pageSize = 50) {
    return request<AffiliateCreatorPage>({
      method: 'get',
      url: `/affiliate-center/reports/${reportId}/creators`,
      params: { shopId, page, pageSize },
    })
  },
  listCreatorMetrics(params: AffiliateCreatorListQuery) {
    return request<AffiliateStableCreatorPage>({
      method: 'get',
      url: '/affiliate-center/creators',
      params,
      timeout: 60_000,
    })
  },
  listVideos(params: AffiliateVideoListQuery) {
    return request<AffiliateVideoPage>({
      method: 'get',
      url: '/affiliate-center/videos',
      params,
      timeout: 60_000,
    })
  },
  listLiveAccounts(params: AffiliateLiveAccountQuery) {
    return request<AffiliateLiveAccountEnvelope>({
      method: 'get',
      url: '/affiliate-center/live-accounts',
      params,
    })
  },
  syncLiveAccounts(data: AffiliateLiveAccountSyncRequest) {
    return request<AffiliateLiveAccountSyncResponse>({
      method: 'post',
      url: '/affiliate-center/live-accounts/sync',
      data,
    })
  },
  getSyncStatus(shopId: string) {
    return request<AffiliateSyncStatusResponse>({
      method: 'get',
      url: '/affiliate-center/sync-status',
      params: { shopId },
    })
  },
  exportLocal(from: string, to: string) {
    return downloadFile('/affiliate-center/local-export', {
      method: 'get',
      params: { from, to },
      timeout: 120_000,
    })
  },
  exportFeishu() {
    return downloadFile('/affiliate-center/feishu-export', {
      method: 'get',
      timeout: 300_000,
    })
  },
  sync(data: AffiliateSyncRequest) {
    return request<AffiliateSyncIntentResponse>({
      method: 'post',
      url: '/affiliate-center/sync',
      data,
    })
  },
  getCreatorDetail(creatorId: string, shopId: string) {
    return request<AffiliateCreatorDetail>({
      method: 'get',
      url: `/affiliate-center/creators/${creatorId}`,
      params: { shopId },
    })
  },
  listCreatorDetailResource(creatorId: string, resource: AffiliateCreatorDetailResource, params: AffiliateStableQuery) {
    return request<AffiliateCreatorDetailPage>({
      method: 'get',
      url: `/affiliate-center/creators/${creatorId}/${resource}`,
      params,
    })
  },
}
