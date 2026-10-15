export type ReturnRequestType = 'return' | 'exchange' | 'refund'
export type ReturnRequestStatus = 'pending_review' | 'approved' | 'rejected' | 'cancelled'

export interface ReturnEligibilityItem {
  orderLineId: string
  sellerSku: string | null
  productName: string
  skuName: string | null
  orderedQuantity: number
  requestedQuantity: number
  availableQuantity: number
}

export interface ReturnEligibility {
  orderId: string
  orderNumber: string
  shopId: string
  items: ReturnEligibilityItem[]
}

export interface ReturnRequestItem {
  id: string
  orderLineId: string
  platformReturnLineId: string | null
  sellerSku: string | null
  productName: string
  skuName: string | null
  requestedQuantity: number
  reasonCode: string
  note: string | null
}

export interface ReturnRma {
  id: string
  rmaNumber: string
  status: 'open' | 'in_transit' | 'received' | 'closed' | 'cancelled'
  reverseTaskId: string | null
  generatedAt: string
}

export interface ReturnRequestRecord {
  id: string
  requestNumber: string
  orderId: string
  orderNumber: string
  shopId: string
  source: 'local' | 'platform'
  platform: string | null
  platformReturnId: string | null
  platformStatus: string | null
  platformReasonText: string | null
  platformCreatedAt: string | null
  platformUpdatedAt: string | null
  refundCurrency: string | null
  refundAmountMinor: number | null
  requestType: ReturnRequestType
  status: ReturnRequestStatus
  reasonCode: string
  customerNote: string | null
  createdByUserId: string | null
  reviewedByUserId: string | null
  reviewNote: string | null
  reviewedAt: string | null
  createdAt: string
  updatedAt: string
  versionId: number
  items: ReturnRequestItem[]
  rma: ReturnRma | null
}

export interface ReturnRequestListResult {
  items: ReturnRequestRecord[]
  total: number
  page: number
  pageSize: number
}

export interface ReturnRequestListParams {
  page: number
  pageSize: number
  shopId?: string
  status?: ReturnRequestStatus
  requestType?: ReturnRequestType
  reason?: string
  appliedFrom?: string
  appliedTo?: string
  rma?: string
}

export interface ReturnRequestCreate {
  orderId: string
  requestType: ReturnRequestType
  reasonCode: string
  customerNote: string | null
  items: Array<{
    orderLineId: string
    requestedQuantity: number
    reasonCode: string
    note: string | null
  }>
}

export interface ReturnReviewRequest {
  decision: 'approve' | 'reject'
  versionId: number
  note: string | null
}

export interface ReturnSyncResult {
  shopId: string
  fetchedCount: number
  upsertedCount: number
  unmatchedOrderCount: number
  unmatchedLineCount: number
}

export interface ReturnShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
}
