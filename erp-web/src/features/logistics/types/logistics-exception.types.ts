export type LogisticsExceptionType =
  'not_picked_up' | 'stalled' | 'address_error' | 'refused' | 'lost' | 'damaged' | 'platform_status_mismatch'

export type LogisticsExceptionStatus = 'open' | 'claimed' | 'escalated' | 'resolved' | 'closed'
export type LogisticsExceptionSeverity = 'low' | 'medium' | 'high' | 'critical'

export interface LogisticsExceptionAction {
  id: string
  actionType: 'detected' | 'claimed' | 'note_added' | 'escalated' | 'resolved' | 'closed'
  actorUserId: string | null
  fromStatus: string | null
  toStatus: string | null
  note: string | null
  details: Record<string, unknown>
  createdAt: string
}

export interface LogisticsException {
  id: string
  exceptionNumber: string
  waybillId: string
  packageId: string
  taskId: string
  taskNumber: string
  sourceNumber: string
  carrierName: string
  trackingNumberMasked: string | null
  exceptionType: LogisticsExceptionType
  status: LogisticsExceptionStatus
  severity: LogisticsExceptionSeverity
  source: 'tracking_event' | 'scheduled_scan'
  title: string
  description: string
  assignedToUserId: string | null
  resolution: string | null
  firstDetectedAt: string
  lastDetectedAt: string
  occurrenceCount: number
  resolvedAt: string | null
  closedAt: string | null
  updatedAt: string
  versionId: number
  actions: LogisticsExceptionAction[]
}

export interface LogisticsExceptionListParams {
  page: number
  pageSize: number
  type?: LogisticsExceptionType
  status?: LogisticsExceptionStatus
  severity?: LogisticsExceptionSeverity
  assignedToMe?: boolean
}

export interface LogisticsExceptionListResult {
  items: LogisticsException[]
  total: number
  page: number
  pageSize: number
}

export interface LogisticsExceptionActionRequest {
  exceptionId: string
  versionId: number
  note?: string
  resolution?: string
  severity?: 'high' | 'critical'
}

export interface PlatformLogisticsSyncResult {
  shopsScanned: number
  ordersScanned: number
  packagesSynced: number
  trackingEventsSynced: number
  failedOrders: number
  exceptionsScanned: number
  exceptionsDetected: number
}
