export type LogisticsTaskStatus =
  | 'pending_review'
  | 'pending_pack'
  | 'pending_waybill'
  | 'pending_dispatch'
  | 'shipped'
  | 'in_transit'
  | 'delivered'
  | 'exception'
  | 'cancelled'

export type LogisticsSourceType = 'sales_order' | 'return' | 'exchange'
export type LogisticsDirection = 'forward' | 'reverse'
export type LogisticsPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface LogisticsTaskItem {
  id: string
  sourceLineId: string
  orderLineId: string | null
  platformProductId: string | null
  platformSkuId: string | null
  sellerSku: string | null
  productName: string
  skuName: string | null
  plannedQuantity: number
  packedQuantity: number
  shippedQuantity: number
}

export interface LogisticsTaskOperation {
  id: string
  operationType: string
  fromStatus: string | null
  toStatus: string | null
  actorUserId: string
  note: string | null
  details: Record<string, unknown>
  createdAt: string
}

export interface LogisticsTaskReview {
  id: string
  result: string
  expectedQuantity: number
  actualQuantity: number
  differences: Array<Record<string, unknown>>
  note: string | null
  reviewerUserId: string
  reviewedAt: string
}

export interface LogisticsTask {
  id: string
  taskNumber: string
  sourceType: LogisticsSourceType
  direction: LogisticsDirection
  sourceId: string
  sourceNumber: string
  orderId: string | null
  rmaId: string | null
  shopId: string | null
  priority: LogisticsPriority
  status: LogisticsTaskStatus
  note: string | null
  createdByUserId: string
  createdAt: string
  updatedAt: string
  versionId: number
  items: LogisticsTaskItem[]
  operations: LogisticsTaskOperation[]
  reviews: LogisticsTaskReview[]
}

export interface LogisticsTaskListParams {
  page: number
  pageSize: number
  status?: LogisticsTaskStatus
  sourceType?: LogisticsSourceType
  shopId?: string
  priority?: LogisticsPriority
  createdFrom?: string
  createdTo?: string
}

export interface LogisticsTaskListResult {
  items: LogisticsTask[]
  total: number
  page: number
  pageSize: number
}

export interface LogisticsTasksGenerateRequest {
  orderId: string
  tasks: Array<{
    items: Array<{ orderLineId: string; plannedQuantity: number }>
    priority: LogisticsPriority
    note: string | null
  }>
}

export interface LogisticsTasksGenerateResponse {
  items: LogisticsTask[]
}

export interface LogisticsReviewRequest {
  items: Array<{
    taskItemId: string
    actualQuantity: number
    differenceReason: LogisticsDifferenceReason | null
  }>
  note: string | null
}

export type LogisticsDifferenceReason = 'shortage' | 'overage' | 'damaged' | 'wrong_sku' | 'other'

export interface LogisticsScanResult {
  code: string
  matchType: 'task' | 'task_item' | 'none'
  tasks: Array<{
    taskId: string
    taskNumber: string
    sourceNumber: string
    status: LogisticsTaskStatus
  }>
  items: Array<{
    taskId: string
    taskNumber: string
    sourceNumber: string
    status: LogisticsTaskStatus
    taskItemId: string
    sellerSku: string | null
    platformSkuId: string | null
    productName: string
    skuName: string | null
    plannedQuantity: number
  }>
}

export interface LogisticsPackageItem {
  id: string
  taskItemId: string
  quantity: number
}

export interface LogisticsPackage {
  id: string
  taskId: string
  packageNumber: string
  status: 'draft' | 'packed' | 'waybill_created' | 'shipped' | 'cancelled'
  weightGrams: number | null
  lengthMm: number | null
  widthMm: number | null
  heightMm: number | null
  note: string | null
  createdByUserId: string
  sealedByUserId: string | null
  sealedAt: string | null
  createdAt: string
  updatedAt: string
  versionId: number
  items: LogisticsPackageItem[]
}

export interface LogisticsPackageDraftCreateRequest {
  note: string | null
}

export interface LogisticsPackageDraftUpdateRequest {
  versionId: number
  items: Array<{ taskItemId: string; quantity: number }>
  weightGrams: number | null
  lengthMm: number | null
  widthMm: number | null
  heightMm: number | null
  note: string | null
}

export interface LogisticsShopOption {
  id: string
  shopName: string
  platform: string
  platformShopId: string
}

export interface LogisticsOrderContext {
  orderId: string
  orderNumber: string
  shopId: string
  shopName: string
  status: string
  externalStatus: string
  buyerUsernameMasked: string | null
  placedAt: string
  maskedRecipient: LogisticsRecipient | null
}

export interface LogisticsRecipient {
  name: string | null
  phone: string | null
  address: string | null
  countryCode: string | null
  purged: boolean
}

export interface LogisticsCarrierService {
  id: string
  carrierId: string
  code: string
  name: string
  serviceLevel: string | null
  supportedCountries: string[]
  platformProviderIds: Record<string, string>
  trackingStatusMap: Record<string, string>
  status: string
  versionId: number
}

export interface LogisticsCarrierAccount {
  id: string
  carrierId: string
  accountName: string
  accountIdentifierMasked: string | null
  authType: string
  status: string
  hasSecret: boolean
  createdAt: string
  updatedAt: string
  versionId: number
}

export interface LogisticsPlatformCarrierMapping {
  id: string
  carrierId: string
  serviceId: string | null
  storeId: string
  platform: string
  region: string
  platformCarrierId: string
  platformCarrierCode: string | null
  platformCarrierName: string | null
  deliveryOptionId: string | null
  rawPayload: Record<string, unknown>
  status: 'active' | 'inactive'
  createdAt: string
  updatedAt: string
  versionId: number
}

export interface LogisticsCarrier {
  id: string
  code: string
  name: string
  adapterKey: string
  status: string
  trackingUrlTemplate: string | null
  createdAt: string
  updatedAt: string
  versionId: number
  services: LogisticsCarrierService[]
  accounts: LogisticsCarrierAccount[]
  platformMappings: LogisticsPlatformCarrierMapping[]
}

export interface LogisticsCarrierCreateRequest {
  code: string
  name: string
  adapterKey: string
  trackingUrlTemplate: string | null
}

export interface LogisticsCarrierServiceCreateRequest {
  code: string
  name: string
  serviceLevel: string | null
  supportedCountries: string[]
  platformProviderIds: Record<string, string>
  trackingStatusMap: Record<string, string>
}

export interface LogisticsPlatformCarrierMappingCreateRequest {
  storeId: string
  platform: string
  region: string
  serviceId: string | null
  platformCarrierId: string
  platformCarrierCode: string | null
  platformCarrierName: string | null
  deliveryOptionId: string | null
  rawPayload?: Record<string, unknown>
}

export interface LogisticsPlatformCarrierMappingUpdateRequest {
  versionId: number
  status?: 'active' | 'inactive'
  platformCarrierId?: string
  platformCarrierCode?: string
  platformCarrierName?: string
  deliveryOptionId?: string
  rawPayload?: Record<string, unknown>
}

export interface LogisticsShippingQuote {
  carrierId: string
  carrierName: string
  serviceId: string
  serviceName: string
  accountId: string | null
  amountMinor: number | null
  currency: string | null
  estimatedDaysMin: number | null
  estimatedDaysMax: number | null
  quoteType: 'calculated' | 'manual'
  warnings: string[]
}

export interface LogisticsWaybill {
  id: string
  packageId: string
  carrierId: string
  serviceId: string | null
  accountId: string | null
  waybillNumber: string
  externalWaybillId: string | null
  trackingNumberMasked: string | null
  trackingStatus: string | null
  trackingOccurredAt: string | null
  trackingLastPolledAt: string | null
  trackingPollErrorCode: string | null
  labelUrl: string | null
  status: 'created' | 'label_ready' | 'shipped' | 'in_transit' | 'delivered' | 'exception' | 'cancelled'
  isCurrent: boolean
  createdAt: string
  updatedAt: string
  versionId: number
}

export interface LogisticsWaybillCreateRequest {
  carrierId: string
  serviceId: string
  accountId: string | null
  trackingNumber: string | null
  externalWaybillId: string | null
}

export interface LogisticsDocument {
  id: string
  documentType: 'shipping_label' | 'carrier_invoice' | 'return_proof'
  ownerType: 'waybill' | 'carrier_invoice' | 'return'
  ownerReferenceId: string
  originalFilename: string
  contentType: string
  sizeBytes: number
  sha256Hex: string
  isCurrent: boolean
  createdByUserId: string
  createdAt: string
  downloadUrl: string
  expiresInSeconds: number
}

export interface LogisticsPackageDispatchRequest {
  packageVersionId: number
  waybillId: string
  waybillVersionId: number
  items: Array<{ taskItemId: string; quantity: number }>
  note: string | null
}

export interface LogisticsPackageDispatchResponse {
  package: LogisticsPackage
  waybill: LogisticsWaybill
  taskId: string
  taskStatus: LogisticsTaskStatus
  taskVersionId: number
  shippedItems: Array<{ taskItemId: string; quantity: number }>
  platformCallbackId: string | null
  platformCallbackQueued: boolean
}
