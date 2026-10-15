import { request } from '@/services/http-client'
import type { LogisticsAlertPhase, LogisticsOrderAlert, LogisticsStatusList, LogisticsStatusLive } from '../types/logistics-status.types'
import type { LogisticsOrderCategory } from '../utils/logistics-order-categories'

export const logisticsStatusApi = {
  sync: (
    params: {
      page: number
      pageSize: number
      shopId?: string
      orderNumber?: string
      category?: LogisticsOrderCategory
      alert?: LogisticsOrderAlert
      alertPhase?: LogisticsAlertPhase
    },
    signal?: AbortSignal,
  ) =>
    request<LogisticsStatusList>({ method: 'post', url: '/logistics/status/sync', params, signal, timeout: 180_000 }),
  exportOrders: (
    params: { shopId?: string; orderNumber?: string; category?: LogisticsOrderCategory; alert?: LogisticsOrderAlert; alertPhase?: LogisticsAlertPhase },
    signal?: AbortSignal,
  ) =>
    request<LogisticsStatusList>({
      method: 'get',
      url: '/logistics/status/export-data',
      params,
      timeout: 120_000,
      signal,
    }),
  list: (params: {
    page: number
    pageSize: number
    shopId?: string
    orderNumber?: string
    category?: LogisticsOrderCategory
    alert?: LogisticsOrderAlert
    alertPhase?: LogisticsAlertPhase
  }) => request<LogisticsStatusList>({ method: 'get', url: '/logistics/status/orders', params, timeout: 30_000 }),
  refresh: (orderId: string, signal?: AbortSignal) =>
    request<LogisticsStatusLive>({
      method: 'post',
      url: `/logistics/status/orders/${orderId}/refresh`,
      signal,
      timeout: 90_000,
    }),
  updateAlertSettings: (leadHours: number) => request<{ leadHours: number; updatedAt: string }>({
    method: 'put', url: '/logistics/status/alert-settings', data: { leadHours },
  }),
}
