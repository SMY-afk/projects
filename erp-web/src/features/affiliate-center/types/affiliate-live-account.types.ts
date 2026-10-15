export type AffiliateLiveSortBy = 'gmv' | 'startedAt'
export type AffiliateLiveSortOrder = 'asc' | 'desc'
export type AffiliateLiveRangePreset = 'today' | 'last7d' | 'last30d' | 'last60d' | 'custom'

export interface AffiliateLiveAccountQuery {
  shopId: string
  page: number
  pageSize: number
  preset: AffiliateLiveRangePreset
  customFrom?: string
  customTo?: string
  sortBy?: AffiliateLiveSortBy
  sortOrder?: AffiliateLiveSortOrder
}

export interface AffiliateLiveAccountSyncRequest {
  shopId: string
  preset: AffiliateLiveRangePreset
  customFrom?: string
  customTo?: string
}

export interface AffiliateLiveAccountSyncResponse {
  items: Array<{ jobId: string; status: 'queued'; existing: boolean }>
  captureMode: 'official_api_owned'
}

export interface AffiliateLiveAccountMetric {
  platformExternalId: string
  fields: Record<string, unknown>
  sourceStatus: string | null
  status: string | null
  sourceUpdatedAt: string | null
  observedAt: string
}

export interface AffiliateLiveAccountEnvelope {
  apiVersion: 'v1'
  source: 'local_detail'
  data: AffiliateLiveAccountMetric[]
  freshness: { isStale: boolean; asOf?: string | null }
  errors: Array<{ code: 'data_unavailable'; message: string; action: 'resync' }>
  pagination: { page: number; pageSize: number; total: number }
}
