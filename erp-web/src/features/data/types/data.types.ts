export interface Money {
  /** Integer in the smallest unit of the stated ISO 4217 currency. */
  amountMinor: number
  currency: string
}

/** A decimal fraction in [0, 1], rounded by the server to four decimal places. */
export type Rate = number

export interface UtcTimeRange {
  /** UTC ISO 8601 instant, for example 2026-08-01T07:00:00Z. */
  from: string
  /** UTC ISO 8601 instant; the interval excludes this boundary. */
  to: string
}

export interface DataMetricValue {
  metric: string
  value: number | Money
  sourceUpdatedAt: string
}

export interface DataQueryContext {
  shopTimezone: string
  range: UtcTimeRange
}

export interface DataFreshness {
  isStale: boolean
  asOf?: string | null
}

export interface DataOperationalError {
  code: 'data_unavailable'
  message: string
  action: 'resync'
}

export interface DataEnvelope<T> {
  apiVersion: 'v1'
  source: 'local_snapshot' | 'local_detail' | 'local_sync' | 'queue'
  data: T
  freshness: DataFreshness
  errors: DataOperationalError[]
}

export type VideoRangePreset = 'today' | 'last7d' | 'last30d' | 'custom'

export interface VideoRange extends UtcTimeRange {
  preset: VideoRangePreset
}

export type VideoCurrency = 'USD' | 'LOCAL'
export type VideoAccountType = 'ALL' | 'OFFICIAL_ACCOUNTS' | 'MARKETING_ACCOUNTS' | 'AFFILIATE_ACCOUNTS'

export interface VideoQuery extends UtcTimeRange {
  shopId: string
  currency: VideoCurrency
  accountType: VideoAccountType
}

export interface VideoRangeMeta {
  windowStart: string
  windowEnd: string
  shopTimezone: string
  isPartial: boolean
  latestAvailableDate?: string | null
}

export interface VideoContentEnvelope extends DataEnvelope<AnalyticsContent[]> {
  range: VideoRangeMeta
}

export interface DataResyncRequest {
  shopId: string
  resourceTypes?: Array<'video' | 'live'>
  windowStart?: string
  windowEnd?: string
  currency?: VideoCurrency
  accountType?: VideoAccountType
}

export interface AnalyticsSnapshot {
  metricSet: string
  granularity: 'day' | 'hour'
  windowStart: string
  windowEnd: string
  currency: string
  metrics: Record<string, unknown>
  sourceUpdatedAt: string | null
  capturedAt: string
}

export interface AnalyticsContent {
  platformExternalId: string
  fields: Record<string, unknown>
  sourceStatus: string | null
  status: string | null
  sourceUpdatedAt: string | null
  observedAt: string
}

export type ContentSortBy = 'gmv' | 'gpm' | 'publishedAt' | 'startedAt'

export interface ContentSort {
  sortBy: ContentSortBy
  sortOrder: 'asc' | 'desc'
}

export interface AnalyticsSyncRun {
  runId: string
  resourceType: string
  status: string
  attemptCount: number
  fetchedCount: number
  persistedCount: number
  errorCategory: string | null
  errorSummary: string | null
  freshAt: string | null
  startedAt: string
  finishedAt: string | null
}

export interface SyncHealth {
  shopId: string
  shopName: string
  resourceType: string
  status: 'healthy' | 'degraded' | 'critical'
  lastSuccessAt: string | null
  delaySeconds: number | null
  failureRate: number | null
  rateLimit429Count: number
  deadLetterCount: number
  dataGapCount: number
  totalRunCount: number
  successfulRunCount: number
  windowHours: number
}

export interface DataShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
  timezone: string | null
}
