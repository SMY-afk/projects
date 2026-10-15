export type BestsellerRoute = 'products' | 'creators' | 'videos' | 'lives'
export type BestsellerEntityType = 'product' | 'creator' | 'video' | 'live'
export type BestsellerTimeSlot = '1D' | '7D' | '30D'
export type BestsellerCurrency = 'USD' | 'LOCAL'
export type BestsellerAuthorType = 'ALL' | 'OFFICIAL' | 'CHANNEL' | 'AFFILIATE'

export type BestsellerErrorCode =
  | 'data_unavailable'
  | 'reauthorization_required'
  | 'not_authorized'
  | 'rate_limited'
  | 'timeout'
  | 'platform_error'
  | 'sync_failed'

export interface BestsellerFreshness {
  isStale: boolean
  asOf?: string | null
  lastErrorAt?: string | null
}

export interface BestsellerSafeError {
  code: BestsellerErrorCode
  message: string
  action: 'resync' | 'reauthorize'
}

export interface BestsellerEnvelope<T> {
  apiVersion: 'v1'
  source: 'local_connection' | 'local_snapshot' | 'queue'
  data: T
  freshness: BestsellerFreshness
  errors: BestsellerSafeError[]
}

export interface BestsellerShop {
  id: string
  shopName: string
  platform: string
  platformShopId: string
  timezone: string | null
}

export interface BestsellerAuthorizationStatus {
  shopId: string
  status: 'ready' | 'reauthorization_required' | 'not_authorized'
  requiredScopes: string[]
  grantedScopes: string[]
  missingScopes: string[]
  canRead: boolean
}

export interface BestsellerQuery {
  shopId: string
  date: string
  timeSlot: BestsellerTimeSlot
  currency: BestsellerCurrency
  authorType?: BestsellerAuthorType
}

export interface BestsellerQueryResponse extends Omit<BestsellerQuery, 'authorType'> {
  market: string | null
  authorType: BestsellerAuthorType | null
}

export interface DesensitizedGmvRange {
  raw: string
  currencyContext: BestsellerCurrency
  computable: false
}

export interface BestsellerEntry {
  entityType: BestsellerEntityType
  externalId: string
  rank: number
  displayName: string | null
  gmv: DesensitizedGmvRange
  extensions: Record<string, unknown>
}

export interface BestsellerListData {
  query: BestsellerQueryResponse
  items: BestsellerEntry[]
}

export interface BestsellerSyncRequest extends BestsellerQuery {
  entityTypes: BestsellerRoute[]
}

export interface BestsellerSyncResult {
  jobIds: string[]
  alreadyQueued: string[]
}
