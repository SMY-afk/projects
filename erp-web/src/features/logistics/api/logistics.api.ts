import { request, uploadFile } from '@/services/http-client'
import type {
  LogisticsCarrier,
  LogisticsCarrierCreateRequest,
  LogisticsCarrierService,
  LogisticsCarrierServiceCreateRequest,
  LogisticsPackage,
  LogisticsPackageDraftCreateRequest,
  LogisticsPackageDraftUpdateRequest,
  LogisticsOrderContext,
  LogisticsRecipient,
  LogisticsReviewRequest,
  LogisticsScanResult,
  LogisticsShopOption,
  LogisticsTask,
  LogisticsTaskListParams,
  LogisticsTaskListResult,
  LogisticsTasksGenerateRequest,
  LogisticsTasksGenerateResponse,
  LogisticsShippingQuote,
  LogisticsWaybill,
  LogisticsWaybillCreateRequest,
  LogisticsDocument,
  LogisticsPackageDispatchRequest,
  LogisticsPackageDispatchResponse,
  LogisticsPlatformCarrierMapping,
  LogisticsPlatformCarrierMappingCreateRequest,
  LogisticsPlatformCarrierMappingUpdateRequest,
} from '../types/logistics.types'
import type {
  LogisticsException,
  LogisticsExceptionListParams,
  LogisticsExceptionListResult,
  PlatformLogisticsSyncResult,
} from '../types/logistics-exception.types'

const normalizeCarrier = (carrier: LogisticsCarrier): LogisticsCarrier => ({
  ...carrier,
  services: carrier.services ?? [],
  accounts: carrier.accounts ?? [],
  platformMappings: carrier.platformMappings ?? [],
})

export const logisticsApi = {
  listExceptions: (params: LogisticsExceptionListParams) =>
    request<LogisticsExceptionListResult>({ method: 'get', url: '/logistics/exceptions', params }),
  getException: (exceptionId: string) =>
    request<LogisticsException>({ method: 'get', url: `/logistics/exceptions/${exceptionId}` }),
  claimException: (exceptionId: string, versionId: number) =>
    request<LogisticsException>({
      method: 'post',
      url: `/logistics/exceptions/${exceptionId}/claim`,
      data: { versionId },
    }),
  noteException: (exceptionId: string, versionId: number, note: string) =>
    request<LogisticsException>({
      method: 'post',
      url: `/logistics/exceptions/${exceptionId}/notes`,
      data: { versionId, note },
    }),
  escalateException: (exceptionId: string, versionId: number, severity: 'high' | 'critical', note: string) =>
    request<LogisticsException>({
      method: 'post',
      url: `/logistics/exceptions/${exceptionId}/escalate`,
      data: { versionId, severity, note },
    }),
  resolveException: (exceptionId: string, versionId: number, resolution: string) =>
    request<LogisticsException>({
      method: 'post',
      url: `/logistics/exceptions/${exceptionId}/resolve`,
      data: { versionId, resolution },
    }),
  closeException: (exceptionId: string, versionId: number, note?: string) =>
    request<LogisticsException>({
      method: 'post',
      url: `/logistics/exceptions/${exceptionId}/close`,
      data: { versionId, note: note || null },
    }),
  detectExceptions: () =>
    request<{ scanned: number; detected: number }>({ method: 'post', url: '/logistics/exceptions/detect' }),
  syncPlatformLogistics: () =>
    request<PlatformLogisticsSyncResult>({ method: 'post', url: '/logistics/exceptions/sync-platform' }),
  listTasks: (params: LogisticsTaskListParams) =>
    request<LogisticsTaskListResult>({ method: 'get', url: '/logistics/tasks', params }),
  getTask: (taskId: string) => request<LogisticsTask>({ method: 'get', url: `/logistics/tasks/${taskId}` }),
  getOrderContext: (taskId: string) =>
    request<LogisticsOrderContext>({ method: 'get', url: `/logistics/tasks/${taskId}/order-context` }),
  getRecipient: (orderId: string) =>
    request<LogisticsRecipient>({ method: 'get', url: `/orders/${orderId}/recipient` }),
  listShops: () => request<LogisticsShopOption[]>({ method: 'get', url: '/logistics/shops' }),
  reviewTask: (taskId: string, data: LogisticsReviewRequest) =>
    request<LogisticsTask>({ method: 'post', url: `/logistics/tasks/${taskId}/reviews`, data }),
  confirmPicking: (taskId: string, note: string | null = null) =>
    request<LogisticsTask>({ method: 'post', url: `/logistics/tasks/${taskId}/picking-completion`, data: { note } }),
  resolveScan: (code: string, taskId?: string) =>
    request<LogisticsScanResult>({ method: 'post', url: '/logistics/scans/resolve', data: { code, taskId } }),
  listPackages: (taskId: string) =>
    request<LogisticsPackage[]>({ method: 'get', url: `/logistics/tasks/${taskId}/packages` }),
  createPackageDraft: (taskId: string, data: LogisticsPackageDraftCreateRequest) =>
    request<LogisticsPackage>({ method: 'post', url: `/logistics/tasks/${taskId}/packages`, data }),
  updatePackageDraft: (packageId: string, data: LogisticsPackageDraftUpdateRequest) =>
    request<LogisticsPackage>({ method: 'patch', url: `/logistics/packages/${packageId}`, data }),
  sealPackage: (packageId: string, versionId: number) =>
    request<LogisticsPackage>({ method: 'post', url: `/logistics/packages/${packageId}/seal`, data: { versionId } }),
  unsealPackage: (packageId: string, versionId: number) =>
    request<LogisticsPackage>({ method: 'post', url: `/logistics/packages/${packageId}/unseal`, data: { versionId } }),
  listCarriers: async () => {
    const records = await request<LogisticsCarrier[]>({ method: 'get', url: '/logistics/carriers' })
    return Array.isArray(records) ? records.map(normalizeCarrier) : []
  },
  createCarrier: (data: LogisticsCarrierCreateRequest) =>
    request<LogisticsCarrier>({ method: 'post', url: '/logistics/carriers', data }),
  createCarrierService: (carrierId: string, data: LogisticsCarrierServiceCreateRequest) =>
    request<LogisticsCarrierService>({
      method: 'post',
      url: `/logistics/carriers/${carrierId}/services`,
      data,
    }),
  createPlatformCarrierMapping: (carrierId: string, data: LogisticsPlatformCarrierMappingCreateRequest) =>
    request<LogisticsPlatformCarrierMapping>({
      method: 'post',
      url: `/logistics/carriers/${carrierId}/platform-mappings`,
      data,
    }),
  updatePlatformCarrierMapping: (mappingId: string, data: LogisticsPlatformCarrierMappingUpdateRequest) =>
    request<LogisticsPlatformCarrierMapping>({
      method: 'patch',
      url: `/logistics/platform-carrier-mappings/${mappingId}`,
      data,
    }),
  quoteShipping: (packageId: string) =>
    request<LogisticsShippingQuote[]>({
      method: 'post',
      url: `/logistics/packages/${packageId}/shipping-quotes`,
      data: {},
    }),
  listWaybills: (packageId: string) =>
    request<LogisticsWaybill[]>({ method: 'get', url: `/logistics/packages/${packageId}/waybills` }),
  createWaybill: (packageId: string, data: LogisticsWaybillCreateRequest) =>
    request<LogisticsWaybill>({ method: 'post', url: `/logistics/packages/${packageId}/waybills`, data }),
  cancelWaybill: (waybillId: string, versionId: number, reason: string) =>
    request<LogisticsWaybill>({
      method: 'post',
      url: `/logistics/waybills/${waybillId}/cancel`,
      data: { versionId, reason },
    }),
  getWaybillLabel: (waybillId: string) =>
    request<LogisticsDocument>({ method: 'get', url: `/logistics/waybills/${waybillId}/label` }),
  uploadWaybillLabel: (waybillId: string, file: File) =>
    uploadFile<LogisticsDocument>(`/logistics/waybills/${waybillId}/label`, file),
  getCarrierInvoiceDocument: (referenceId: string) =>
    request<LogisticsDocument>({
      method: 'get',
      url: `/logistics/carrier-invoices/${referenceId}/document`,
    }),
  uploadCarrierInvoiceDocument: (referenceId: string, file: File) =>
    uploadFile<LogisticsDocument>(`/logistics/carrier-invoices/${referenceId}/document`, file),
  getReturnProofDocument: (referenceId: string) =>
    request<LogisticsDocument>({ method: 'get', url: `/logistics/return-proofs/${referenceId}/document` }),
  uploadReturnProofDocument: (referenceId: string, file: File) =>
    uploadFile<LogisticsDocument>(`/logistics/return-proofs/${referenceId}/document`, file),
  dispatchPackage: (packageId: string, data: LogisticsPackageDispatchRequest) =>
    request<LogisticsPackageDispatchResponse>({
      method: 'post',
      url: `/logistics/packages/${packageId}/dispatch`,
      data,
    }),
  generateTasks: (data: LogisticsTasksGenerateRequest) =>
    request<LogisticsTasksGenerateResponse>({ method: 'post', url: '/logistics/tasks/generate', data }),
}
