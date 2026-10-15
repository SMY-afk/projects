import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { returnsApi } from '../api/returns.api'
import type { ReturnRequestCreate, ReturnRequestListParams, ReturnReviewRequest } from '../types/returns.types'

export const returnsQueryKeys = {
  all: ['returns'] as const,
  shops: ['returns', 'shops'] as const,
  list: (params: ReturnRequestListParams) => ['returns', 'list', params] as const,
  detail: (requestId: string) => ['returns', 'detail', requestId] as const,
}

export const useReturnShopsQuery = () =>
  useQuery({ queryKey: returnsQueryKeys.shops, queryFn: () => returnsApi.listShops() })

export const useReturnRequestsQuery = (params: ReturnRequestListParams) =>
  useQuery({ queryKey: returnsQueryKeys.list(params), queryFn: () => returnsApi.list(params) })

export const useReturnRequestQuery = (requestId: string) =>
  useQuery({
    queryKey: returnsQueryKeys.detail(requestId),
    queryFn: () => returnsApi.get(requestId),
    enabled: Boolean(requestId),
  })

export function useCreateReturnRequestMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ReturnRequestCreate) => returnsApi.create(data),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: returnsQueryKeys.all }),
  })
}

export function useReviewReturnRequestMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ requestId, data }: { requestId: string; data: ReturnReviewRequest }) =>
      returnsApi.review(requestId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: returnsQueryKeys.all })
      await queryClient.invalidateQueries({ queryKey: ['logistics'] })
    },
  })
}

export function useSyncReturnRequestsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (shopId: string) => returnsApi.sync(shopId),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: returnsQueryKeys.all }),
  })
}
