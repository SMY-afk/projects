import { request } from '@/services/http-client'
import type {
  ReturnEligibility,
  ReturnRequestCreate,
  ReturnRequestListParams,
  ReturnRequestListResult,
  ReturnRequestRecord,
  ReturnReviewRequest,
  ReturnShopOption,
  ReturnSyncResult,
} from '../types/returns.types'

export const returnsApi = {
  listShops: () => request<ReturnShopOption[]>({ method: 'get', url: '/shops' }),
  getEligibility: (orderReference: string) =>
    request<ReturnEligibility>({
      method: 'get',
      url: '/returns/eligibility',
      params: { orderReference },
    }),
  list: (params: ReturnRequestListParams) =>
    request<ReturnRequestListResult>({ method: 'get', url: '/returns/requests', params }),
  get: (requestId: string) => request<ReturnRequestRecord>({ method: 'get', url: `/returns/${requestId}` }),
  create: (data: ReturnRequestCreate) => request<ReturnRequestRecord>({ method: 'post', url: '/returns', data }),
  review: (requestId: string, data: ReturnReviewRequest) =>
    request<ReturnRequestRecord>({ method: 'post', url: `/returns/${requestId}/review`, data }),
  sync: (shopId: string) => request<ReturnSyncResult>({ method: 'post', url: '/returns/sync', data: { shopId } }),
}
