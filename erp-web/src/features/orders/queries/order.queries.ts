import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { orderApi } from '../api/order.api'
import type { OrderListParams } from '../types/order.types'

export const orderQueryKeys = {
  all: ['orders'] as const,
  list: (params: OrderListParams) => ['orders', 'list', params] as const,
  detail: (orderId: string) => ['orders', 'detail', orderId] as const,
  shops: ['orders', 'shops'] as const,
}

export const useOrderListQuery = (params: OrderListParams) =>
  useQuery({
    queryKey: orderQueryKeys.list(params),
    queryFn: ({ signal }) => orderApi.getList(params, signal),
    placeholderData: keepPreviousData,
    gcTime: 2 * 60 * 1000,
  })

export const useOrderDetailQuery = (orderId: string) =>
  useQuery({
    queryKey: orderQueryKeys.detail(orderId),
    queryFn: () => orderApi.getDetail(orderId),
    enabled: Boolean(orderId),
  })

export const useOrderShopOptionsQuery = () =>
  useQuery({ queryKey: orderQueryKeys.shops, queryFn: () => orderApi.listShops() })
