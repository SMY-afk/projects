import { request } from '@/services/http-client'
import { isDataMockEnabled } from '@/services/api-mode'
import type {
  AnalyticsContent,
  AnalyticsSnapshot,
  ContentSort,
  AnalyticsSyncRun,
  DataEnvelope,
  DataResyncRequest,
  DataShopOption,
  SyncHealth,
  VideoContentEnvelope,
  VideoQuery,
} from '../types/data.types'

export interface AnalyticsQuery {
  shopId: string
  from: string
  to: string
  currency: string
  granularity: 'day' | 'hour'
}

const paramsFor = ({ shopId, from, to, currency, granularity }: AnalyticsQuery) => ({
  shopId,
  from,
  to,
  currency,
  granularity,
})

export interface DataApi {
  listShops(): Promise<DataShopOption[]>
  overview(query: AnalyticsQuery): Promise<DataEnvelope<AnalyticsSnapshot[]>>
  trends(query: AnalyticsQuery): Promise<DataEnvelope<AnalyticsSnapshot[]>>
  videos(query: VideoQuery, sort: ContentSort): Promise<VideoContentEnvelope>
  lives(shopId: string, sort: ContentSort): Promise<DataEnvelope<AnalyticsContent[]>>
  syncStatus(shopId: string): Promise<DataEnvelope<AnalyticsSyncRun[]>>
  syncHealth(shopId: string): Promise<SyncHealth[]>
  resync(payload: DataResyncRequest): Promise<DataEnvelope<{ jobIds: string[]; alreadyQueued: string[] }>>
}

const httpDataApi: DataApi = {
  listShops: () => request<DataShopOption[]>({ method: 'get', url: '/shops' }),
  overview: (query: AnalyticsQuery) =>
    request<DataEnvelope<AnalyticsSnapshot[]>>({ method: 'get', url: '/data/overview', params: paramsFor(query) }),
  trends: (query: AnalyticsQuery) =>
    request<DataEnvelope<AnalyticsSnapshot[]>>({
      method: 'get',
      url: '/data/trends',
      params: { ...paramsFor(query), metricSet: 'trend' },
    }),
  videos: (query: VideoQuery, sort: ContentSort) =>
    request<VideoContentEnvelope>({ method: 'get', url: '/data/videos', params: { ...query, ...sort } }),
  lives: (shopId: string, sort: ContentSort) =>
    request<DataEnvelope<AnalyticsContent[]>>({ method: 'get', url: '/data/lives', params: { shopId, ...sort } }),
  syncStatus: (shopId: string) =>
    request<DataEnvelope<AnalyticsSyncRun[]>>({ method: 'get', url: '/data/sync-status', params: { shopId } }),
  syncHealth: (shopId: string) => request<SyncHealth[]>({ method: 'get', url: '/sync-health', params: { shopId } }),
  resync: (payload: DataResyncRequest) =>
    request<DataEnvelope<{ jobIds: string[]; alreadyQueued: string[] }>>({
      method: 'post',
      url: '/data/resync',
      data: payload,
    }),
}

const mockTime = '2026-08-17T08:00:00Z'
const mockEnvelope = <T>(source: DataEnvelope<T>['source'], data: T): DataEnvelope<T> => ({
  apiVersion: 'v1',
  source,
  data,
  freshness: { isStale: false, asOf: mockTime },
  errors: [],
})
const resolved = <T>(value: T) => Promise.resolve(value)

const mockDataApi: DataApi = {
  listShops: () =>
    resolved([
      {
        id: 'data-mock-shop',
        shopName: 'Mock TikTok Shop',
        platform: 'tiktok',
        platformShopId: 'mock-shop',
        timezone: 'America/Los_Angeles',
      },
    ]),
  overview: () =>
    resolved(
      mockEnvelope('local_snapshot', [
        {
          metricSet: 'overview',
          granularity: 'day',
          windowStart: mockTime,
          windowEnd: mockTime,
          currency: 'USD',
          metrics: { views: 128, orders: 6, gmv: { amountMinor: 259900, currency: 'USD' } },
          sourceUpdatedAt: mockTime,
          capturedAt: mockTime,
        },
      ]),
    ),
  trends: () =>
    resolved(
      mockEnvelope(
        'local_snapshot',
        [0, 1, 2].map((index) => ({
          metricSet: 'trend',
          granularity: 'day',
          windowStart: `2026-08-${String(15 + index).padStart(2, '0')}T00:00:00Z`,
          windowEnd: `2026-08-${String(16 + index).padStart(2, '0')}T00:00:00Z`,
          currency: 'USD',
          metrics: { gmv: { amountMinor: 180000 + index * 42000, currency: 'USD' } },
          sourceUpdatedAt: mockTime,
          capturedAt: mockTime,
        })),
      ),
    ),
  videos: (query) =>
    resolved({
      ...mockEnvelope('local_detail', [
        {
          platformExternalId: 'mock-video-001',
          fields: {
            title: '夏日新品开箱',
            creatorNickname: 'Mock Creator',
            gmvAmount: '2599.00',
            gmvCurrency: 'USD',
            gpmAmount: '20.30',
            gpmCurrency: 'USD',
            videoPostTime: mockTime,
          },
          sourceStatus: 'published',
          status: 'published',
          sourceUpdatedAt: mockTime,
          observedAt: mockTime,
        },
      ]),
      range: {
        windowStart: query.from,
        windowEnd: query.to,
        shopTimezone: 'America/Los_Angeles',
        isPartial: false,
      },
    }),
  lives: () =>
    resolved(
      mockEnvelope('local_detail', [
        {
          platformExternalId: 'mock-live-001',
          fields: {
            title: '新品专场直播',
            startTime: '2026-08-17T06:00:00Z',
            endTime: mockTime,
            gmvAmount: '3890.00',
            gmvCurrency: 'USD',
            skuOrders: 42,
            itemsSold: 51,
            customers: 38,
            averagePriceAmount: '102.37',
            averagePriceCurrency: 'USD',
          },
          sourceStatus: 'ended',
          status: 'ended',
          sourceUpdatedAt: mockTime,
          observedAt: mockTime,
        },
      ]),
    ),
  syncStatus: () =>
    resolved(
      mockEnvelope('local_sync', [
        {
          runId: 'mock-run-001',
          resourceType: 'video',
          status: 'succeeded',
          attemptCount: 1,
          fetchedCount: 1,
          persistedCount: 1,
          errorCategory: null,
          errorSummary: null,
          freshAt: mockTime,
          startedAt: mockTime,
          finishedAt: mockTime,
        },
      ]),
    ),
  syncHealth: () =>
    resolved([
      {
        shopId: 'data-mock-shop',
        shopName: 'Mock TikTok Shop',
        resourceType: 'video',
        status: 'healthy',
        lastSuccessAt: mockTime,
        delaySeconds: 0,
        failureRate: 0,
        rateLimit429Count: 0,
        deadLetterCount: 0,
        dataGapCount: 0,
        totalRunCount: 1,
        successfulRunCount: 1,
        windowHours: 168,
      },
    ]),
  resync: () => resolved(mockEnvelope('queue', { jobIds: ['mock-job-001'], alreadyQueued: [] })),
}

export const dataApi = isDataMockEnabled() ? mockDataApi : httpDataApi
export const isDataMock = isDataMockEnabled()
