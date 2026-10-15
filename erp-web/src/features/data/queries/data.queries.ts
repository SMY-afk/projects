import { useMutation, useQuery } from '@tanstack/react-query'
import { dataApi, type AnalyticsQuery } from '../api/data.api'
import type { ContentSort, DataResyncRequest, VideoQuery } from '../types/data.types'

const autoResyncAt = new Map<string, number>()
const autoResyncCooldownMs = 60_000

export const dataQueryKeys = {
  shops: ['data', 'shops'] as const,
  overview: (query: AnalyticsQuery) => ['data', 'overview', query] as const,
  trends: (query: AnalyticsQuery) => ['data', 'trends', query] as const,
  videos: (query: VideoQuery | undefined, sort: ContentSort) =>
    ['data', 'videos', query?.shopId, query?.from, query?.to, query?.currency, query?.accountType, sort] as const,
  lives: (shopId: string | undefined, sort: ContentSort) => ['data', 'lives', shopId, sort] as const,
  sync: (shopId?: string) => ['data', 'sync', shopId] as const,
  syncHealth: (shopId?: string) => ['data', 'sync-health', shopId] as const,
}

export const useDataShopOptionsQuery = () =>
  useQuery({ queryKey: dataQueryKeys.shops, queryFn: () => dataApi.listShops() })
export const useOverviewQuery = (query: AnalyticsQuery, enabled: boolean) =>
  useQuery({ queryKey: dataQueryKeys.overview(query), queryFn: () => dataApi.overview(query), enabled })
export const useTrendsQuery = (query: AnalyticsQuery, enabled: boolean) =>
  useQuery({ queryKey: dataQueryKeys.trends(query), queryFn: () => dataApi.trends(query), enabled })
export const useVideosQuery = (query: VideoQuery | undefined, sort: ContentSort) =>
  useQuery({
    queryKey: dataQueryKeys.videos(query, sort),
    queryFn: async () => {
      const response = await dataApi.videos(query!, sort)
      if (response.freshness.isStale) queueMissingVideoRange(query!)
      return response
    },
    enabled: Boolean(query),
    staleTime: 0,
    refetchInterval: (result) => (result.state.data?.freshness.isStale ? 3_000 : false),
  })
export const useLivesQuery = (shopId: string | undefined, sort: ContentSort) =>
  useQuery({
    queryKey: dataQueryKeys.lives(shopId, sort),
    queryFn: () => dataApi.lives(shopId!, sort),
    enabled: Boolean(shopId),
  })
export const useSyncStatusQuery = (shopId?: string) =>
  useQuery({
    queryKey: dataQueryKeys.sync(shopId),
    queryFn: () => dataApi.syncStatus(shopId!),
    enabled: Boolean(shopId),
  })
export const useSyncHealthQuery = (shopId?: string) =>
  useQuery({
    queryKey: dataQueryKeys.syncHealth(shopId),
    queryFn: () => dataApi.syncHealth(shopId!),
    enabled: Boolean(shopId),
  })
export const useResyncMutation = () =>
  useMutation({ mutationFn: (payload: DataResyncRequest) => dataApi.resync(payload) })

function queueMissingVideoRange(query: VideoQuery) {
  const key = `${query.shopId}:${query.from}:${query.to}:${query.currency}:${query.accountType}`
  const now = Date.now()
  if (now - (autoResyncAt.get(key) ?? 0) < autoResyncCooldownMs) return
  autoResyncAt.set(key, now)
  void dataApi
    .resync({
      shopId: query.shopId,
      resourceTypes: ['video'],
      windowStart: query.from,
      windowEnd: query.to,
      currency: query.currency,
      accountType: query.accountType,
    })
    .catch(() => autoResyncAt.delete(key))
}
