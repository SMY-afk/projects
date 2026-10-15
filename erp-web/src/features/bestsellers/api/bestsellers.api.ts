import { request } from '@/services/http-client'
import { isBestsellersMockEnabled } from '@/services/api-mode'
import type {
  BestsellerAuthorizationStatus,
  BestsellerEnvelope,
  BestsellerEntry,
  BestsellerListData,
  BestsellerQuery,
  BestsellerRoute,
  BestsellerShop,
  BestsellerSyncRequest,
  BestsellerSyncResult,
} from '../types/bestseller.types'

export interface BestsellersApi {
  listShops(): Promise<BestsellerShop[]>
  authorizationStatus(shopId: string): Promise<BestsellerEnvelope<BestsellerAuthorizationStatus>>
  reauthorizationUrl(shopId: string): Promise<{ authorizationUrl: string }>
  list(entity: BestsellerRoute, query: BestsellerQuery): Promise<BestsellerEnvelope<BestsellerListData>>
  sync(payload: BestsellerSyncRequest): Promise<BestsellerEnvelope<BestsellerSyncResult>>
}

const httpApi: BestsellersApi = {
  listShops: () => request<BestsellerShop[]>({ method: 'get', url: '/shops' }),
  authorizationStatus: (shopId) =>
    request<BestsellerEnvelope<BestsellerAuthorizationStatus>>({
      method: 'get',
      url: '/bestsellers/authorization-status',
      params: { shopId },
    }),
  reauthorizationUrl: (shopId) =>
    request<{ authorizationUrl: string }>({
      method: 'post',
      url: `/v1/shops/tiktok/${shopId}/reauthorization-url`,
    }),
  list: (entity, query) =>
    request<BestsellerEnvelope<BestsellerListData>>({
      method: 'get',
      url: `/bestsellers/${entity}`,
      params: query,
    }),
  sync: (payload) =>
    request<BestsellerEnvelope<BestsellerSyncResult>>({ method: 'post', url: '/bestsellers/sync', data: payload }),
}

const mockAsOf = '2026-08-20T04:00:00Z'
const mockShop: BestsellerShop = {
  id: 'bestsellers-mock-shop',
  shopName: 'Akeleo Fun Toys',
  platform: 'tiktok',
  platformShopId: 'mock-platform-shop',
  timezone: 'America/Los_Angeles',
}

const mockEntries: Record<BestsellerRoute, BestsellerEntry[]> = {
  products: [
    {
      entityType: 'product',
      externalId: 'product-001',
      rank: 1,
      displayName: 'Construction Truck Set',
      gmv: { raw: '$97K ~ $191K', currencyContext: 'USD', computable: false },
      extensions: { product_image: { thumb_urls: ['https://placehold.co/72x72?text=Top+1'] } },
    },
  ],
  creators: [
    {
      entityType: 'creator',
      externalId: 'creator-open-id-001',
      rank: 1,
      displayName: 'Toy Trends Creator',
      gmv: { raw: '$51K ~ $96K', currencyContext: 'USD', computable: false },
      extensions: { user_name: 'toy_trends', followers_count: 128000, likes_count: 2400000 },
    },
  ],
  videos: [
    {
      entityType: 'video',
      externalId: 'video-001',
      rank: 1,
      displayName: 'Toy Trends Creator',
      gmv: { raw: '$32K ~ $50K', currencyContext: 'USD', computable: false },
      extensions: {
        views: 820000,
        likes: 46000,
        comments: 3200,
        shares: 1800,
        publish_time: 1787097600,
        product_infos: [{ product_id: 'product-001', product_name: 'Construction Truck Set' }],
      },
    },
  ],
  lives: [
    {
      entityType: 'live',
      externalId: 'live-001',
      rank: 1,
      displayName: 'New Toys Live',
      gmv: { raw: '$18K ~ $31K', currencyContext: 'USD', computable: false },
      extensions: {},
    },
  ],
}

const envelope = <T>(source: BestsellerEnvelope<T>['source'], data: T): BestsellerEnvelope<T> => ({
  apiVersion: 'v1',
  source,
  data,
  freshness: { isStale: false, asOf: mockAsOf },
  errors: [],
})

const mockApi: BestsellersApi = {
  listShops: () => Promise.resolve([mockShop]),
  authorizationStatus: (shopId) =>
    Promise.resolve(
      envelope('local_connection', {
        shopId,
        status: 'ready',
        requiredScopes: ['data.bestselling.public.read'],
        grantedScopes: ['data.bestselling.public.read'],
        missingScopes: [],
        canRead: true,
      }),
    ),
  reauthorizationUrl: (shopId) =>
    Promise.resolve({ authorizationUrl: `https://example.test/reauthorize?shopId=${shopId}` }),
  list: (entity, query) =>
    Promise.resolve(
      envelope('local_snapshot', {
        query: { ...query, market: 'US', authorType: query.authorType ?? null },
        items: mockEntries[entity],
      }),
    ),
  sync: () => Promise.resolve(envelope('queue', { jobIds: ['mock-bestseller-job'], alreadyQueued: [] })),
}

export const isBestsellersMock = isBestsellersMockEnabled()
export const bestsellersApi = isBestsellersMock ? mockApi : httpApi
