import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { bestsellersApi } from '../api/bestsellers.api'
import type { BestsellerQuery, BestsellerRoute, BestsellerSyncRequest } from '../types/bestseller.types'

export const bestsellerQueryKeys = {
  all: ['bestsellers'] as const,
  shops: ['bestsellers', 'shops'] as const,
  authorization: (shopId?: string) => ['bestsellers', 'authorization', shopId] as const,
  listPrefix: (shopId: string) => ['bestsellers', 'list', shopId] as const,
  list: (entity: BestsellerRoute, query: BestsellerQuery) =>
    [
      'bestsellers',
      'list',
      query.shopId,
      entity,
      query.date,
      query.timeSlot,
      query.currency,
      query.authorType ?? 'NONE',
    ] as const,
}

export const useBestsellerShopsQuery = () =>
  useQuery({ queryKey: bestsellerQueryKeys.shops, queryFn: () => bestsellersApi.listShops() })

export const useBestsellerAuthorizationQuery = (shopId?: string) =>
  useQuery({
    queryKey: bestsellerQueryKeys.authorization(shopId),
    queryFn: () => bestsellersApi.authorizationStatus(shopId!),
    enabled: Boolean(shopId),
  })

export const useBestsellerListQuery = (
  query: BestsellerQuery,
  entity: BestsellerRoute,
  enabled: boolean,
  polling = false,
) =>
  useQuery({
    queryKey: bestsellerQueryKeys.list(entity, query),
    queryFn: () => bestsellersApi.list(entity, query),
    enabled,
    refetchInterval: polling ? 3_000 : false,
  })

export const useBestsellerSyncMutation = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: BestsellerSyncRequest) => bestsellersApi.sync(payload),
    onSuccess: (_, payload) =>
      queryClient.invalidateQueries({ queryKey: bestsellerQueryKeys.listPrefix(payload.shopId) }),
  })
}

export const useBestsellerReauthorizationMutation = () =>
  useMutation({ mutationFn: (shopId: string) => bestsellersApi.reauthorizationUrl(shopId) })
