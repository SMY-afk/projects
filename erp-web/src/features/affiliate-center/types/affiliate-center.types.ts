export type AffiliateCenterResource = 'creators' | 'videos'

export interface AffiliateResourceDefinition {
  key: AffiliateCenterResource
  label: string
}

export interface AffiliateResourceContract {
  items: AffiliateResourceDefinition[]
  queryDimensions: ['shopId', 'windowStart', 'windowEnd', 'shopTimezone', 'currency', 'filters']
  windowSemantics: 'inclusive_shop_local_dates'
  display: Record<AffiliateCenterResource, AffiliateResourceDisplay>
  capturePolicy: AffiliateCapturePolicy
}

export interface AffiliateDisplayMetric {
  field: string
  label: string
  definition: string
  valueType: 'string' | 'money_minor' | 'integer' | 'decimal_ratio'
  unit: string
  displayUnit?: string
  currencySource?: 'query.currency'
  windowScope: 'identity' | 'query_window' | 'observation_at_report_generation'
  nullDisplay: '—'
}

export interface AffiliateResourceDisplay {
  status: 'active' | 'awaiting_verified_payload'
  rowGrain: string
  currencySource: 'query.currency'
  windowSemantics: 'inclusive_shop_local_dates'
  metrics: AffiliateDisplayMetric[]
  defaultSort: Array<{ field: string; direction: 'asc' | 'desc' }>
  sorting?: {
    scope: string
    execution: 'server_side'
    nulls: 'last'
    tieBreaker: string
  }
  activationRule?: string
}

export interface AffiliateCapturePolicy {
  executionBoundary: 'current_browser_session_only'
  browserCredentialTransfer: 'prohibited'
  backendHandoff: 'sanitized_business_response_only'
  rawResponseTtlDays: 7
  logFieldAllowlist: string[]
  forbiddenFields: string[]
  completeness: {
    terminalRule: 'has_more_false_or_next_cursor_empty'
    countRule: 'unique_record_count_equals_total_count_when_present'
    mismatchStatus: 'partial'
  }
}

export interface AffiliateQueryDimensions {
  shopId: string
  windowStart: string
  windowEnd: string
  shopTimezone: string
  currency: string
  filters: Record<string, unknown>
}

export interface AffiliateShop {
  id: string
  shopName: string
  timezone: string | null
  currency: string | null
}

export interface AffiliateCreatorReport extends AffiliateQueryDimensions {
  id: string
  resource: 'creators'
  scopeLabel: string
  sourceKind: string
  sourceFilename: string
  revisionNo: number
  status: 'running' | 'complete' | 'partial'
  completenessReason: string | null
  rowCount: number
  capturedAt?: string
  importedAt?: string
  duplicate?: boolean
}

export interface AffiliateCreatorMetric {
  id: string
  username: string
  creatorOpenId: string | null
  avatarUrl?: string | null
  affiliateGmvMinor: number
  affiliateLiveGmvMinor: number
  affiliateVideoGmvMinor: number
  affiliateShowcaseGmvMinor: number
  affiliateProductItemsSold: number | null
  itemsSold: number
  estimatedCommissionMinor: number
  estimatedFlatFeeMinor: number | null
  averageOrderAmountMinor: number | null
  showcaseProductCount: number
  affiliateOrderCount: number
  clickThroughRate: string | null
  productImpressions: number
  averageAffiliateCustomers: string | number | null
  affiliateLiveCount: number
  affiliateVideoCount: number
  targetCollaborationGmvMinor: number
  targetCollaborationEstimatedCommissionMinor: number
  openCollaborationGmvMinor: number
  openCollaborationEstimatedCommissionMinor: number
  refundedAffiliateGmvMinor: number
  refundedAffiliateProductCount: number
  affiliateFollowerCount: number | null
}

export interface AffiliateCreatorPage {
  report: AffiliateCreatorReport
  items: AffiliateCreatorMetric[]
  page: number
  pageSize: number
  total: number
}

export type AffiliateSortOrder = 'asc' | 'desc'
export type AffiliateCreatorSort =
  | 'username'
  | 'affiliateGmvMinor'
  | 'estimatedCommissionMinor'
  | 'affiliateOrderCount'
  | 'itemsSold'
  | 'productImpressions'
  | 'clickThroughRate'
  | 'affiliateVideoCount'
  | 'affiliateFollowerCount'
export type AffiliateVideoSort =
  | 'gmvMinor'
  | 'estimatedCommissionMinor'
  | 'orderCount'
  | 'itemsSold'
  | 'productImpressions'
  | 'views'
  | 'videoPostTime'

export interface AffiliateStableQuery {
  shopId: string
  from: string
  to: string
  currency: string
  page?: number
  pageSize?: number
  order?: AffiliateSortOrder
}

export interface AffiliateCreatorListQuery extends AffiliateStableQuery {
  sort?: AffiliateCreatorSort
}

export interface AffiliateStableCreatorPage extends Omit<AffiliateCreatorPage, 'report'> {
  report: AffiliateCreatorReport | null
  summary: AffiliateCreatorSummary
  sort: AffiliateCreatorSort
  order: AffiliateSortOrder
}

export interface AffiliateCreatorSummary {
  creatorCount: number
  affiliateGmvMinor: number
  estimatedCommissionMinor: number
  itemsSold: number
  affiliateOrderCount: number
  productImpressions: number
}

export interface AffiliateVideoListQuery extends AffiliateStableQuery {
  sort?: AffiliateVideoSort
  creatorOpenId?: string
}

export interface AffiliateVideoProduct {
  productId: string
  title: string | null
  coverImageUrl: string | null
}

export interface AffiliateVideoMetric extends Record<string, unknown> {
  id: string
  videoId: string
  title?: string | null
  coverImageUrl?: string | null
  creatorOpenId?: string | null
  creatorUsername?: string | null
  creatorNickname?: string | null
  creatorAvatarUrl?: string | null
  videoPostTime?: string | null
  promotedProducts?: AffiliateVideoProduct[]
  promotedProductIds?: string[]
  views?: number | null
  gmvMinor?: number | null
  orderCount?: number | null
  productClickThroughRate?: string | null
}

export interface AffiliateVideoPage {
  run: AffiliateSyncRun | null
  query: AffiliateQueryDimensions
  items: AffiliateVideoMetric[]
  page: number
  pageSize: number
  total: number
  summary: AffiliateVideoSummary
  sort: AffiliateVideoSort
  order: AffiliateSortOrder
}

export interface AffiliateVideoSummary {
  videoCount: number
  gmvMinor: number
  orderCount: number
  itemsSold: number
  views: number
  productImpressions: number
}

export interface AffiliateSyncRun {
  runId: string
  sourceKind?: string | null
  status: string
  fetchedCount: number
  persistedCount: number
  startedAt: string
  finishedAt: string | null
  freshAt: string | null
  errorCategory: string | null
  errorSummary: string | null
}

export interface AffiliateResourceSyncStatus {
  resource: AffiliateCenterResource
  resourceType: 'affiliate_creator' | 'affiliate_video' | 'video'
  status: string
  latestRun: AffiliateSyncRun | null
  lastFailureRun: AffiliateSyncRun | null
  lastCompleteRunId: string | null
  lastCompleteAt: string | null
}

export type AffiliateBrowserHealthState = 'browser_offline' | 'connecting' | 'online' | 'session_expired' | 'captcha'

export interface AffiliateBrowserHealth {
  state: AffiliateBrowserHealthState
  cdpAvailable: boolean
  sessionAvailable: boolean
  updatedAt: string
  recoveredAt: string | null
  latestAvailableDate: string | null
  latestAvailableDates?: Partial<Record<AffiliateCenterResource, string | null>>
}

export interface AffiliateSyncStatusResponse {
  items: AffiliateResourceSyncStatus[]
  sourceKind?: 'page_capture' | 'official_api'
  captureMode?: 'browser_daemon_owned' | 'official_api_owned'
  latestAvailableDates?: Partial<Record<AffiliateCenterResource, string | null>>
  browser: AffiliateBrowserHealth | null
}

export interface AffiliateSyncRequest {
  shopId: string
  from: string
  to: string
  currency: string
  resources?: AffiliateCenterResource[]
}

export interface AffiliateSyncIntent {
  runId: string
  resource: AffiliateCenterResource
  resourceType: 'affiliate_creator' | 'affiliate_video'
  status: 'queued' | 'running' | 'succeeded'
  existing: boolean
}

export interface AffiliateSyncIntentResponse {
  items: AffiliateSyncIntent[]
  captureMode: 'browser_daemon_owned' | 'official_api_owned'
}

export type AffiliateCreatorDetailResource = 'video' | 'live' | 'product' | 'product-card'

export interface AffiliateCreatorProfile {
  id: string
  username: string
  creatorOpenId: string | null
  avatarUrl: string | null
  firstSeenAt: string
  lastSeenAt: string
}

export interface AffiliateCreatorDetailReport {
  id: string
  resource: string
  status: 'running' | 'complete' | 'partial'
  revisionNo: number
  expectedTotal: number | null
  recordsUnique: number
  capturedAt: string
  finishedAt: string | null
  completenessReason: string | null
  currency: string
  shopTimezone: string
}

export interface AffiliateCreatorDetailStatus {
  resource: string
  status: string
  report: AffiliateCreatorDetailReport | null
}

export interface AffiliateCreatorDetail {
  creator: AffiliateCreatorProfile
  resources: AffiliateCreatorDetailStatus[]
}

export interface AffiliateCreatorDetailItem extends Record<string, unknown> {
  id: string
  title?: string | null
  coverImageUrl?: string | null
  publishedAt?: string | null
  gmvMinor?: number | null
  estimatedCommissionMinor?: number | null
  orderCount?: number | null
  itemsSold?: number | null
  buyerCount?: number | null
  productImpressions?: number | null
  productClicks?: number | null
  views?: number | null
  productClickThroughRate?: string | null
}

export interface AffiliateCreatorDetailPage {
  report: AffiliateCreatorDetailReport | null
  items: AffiliateCreatorDetailItem[]
  page: number
  pageSize: number
  total: number
}
