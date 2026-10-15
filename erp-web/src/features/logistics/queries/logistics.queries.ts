import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { logisticsApi } from '../api/logistics.api'
import type {
  LogisticsCarrierCreateRequest,
  LogisticsCarrierServiceCreateRequest,
  LogisticsPackageDraftCreateRequest,
  LogisticsPackageDraftUpdateRequest,
  LogisticsPackageDispatchRequest,
  LogisticsPlatformCarrierMappingCreateRequest,
  LogisticsPlatformCarrierMappingUpdateRequest,
  LogisticsReviewRequest,
  LogisticsTaskListParams,
  LogisticsWaybillCreateRequest,
} from '../types/logistics.types'
import type { LogisticsExceptionActionRequest, LogisticsExceptionListParams } from '../types/logistics-exception.types'

export const logisticsQueryKeys = {
  all: ['logistics'] as const,
  tasks: (params: LogisticsTaskListParams) => ['logistics', 'tasks', params] as const,
  task: (taskId: string) => ['logistics', 'task', taskId] as const,
  packages: (taskId: string) => ['logistics', 'task', taskId, 'packages'] as const,
  orderContext: (taskId: string) => ['logistics', 'task', taskId, 'order-context'] as const,
  shops: ['logistics', 'shops'] as const,
  carriers: ['logistics', 'carriers'] as const,
  waybills: (packageId: string) => ['logistics', 'package', packageId, 'waybills'] as const,
  exceptions: (params: LogisticsExceptionListParams) => ['logistics', 'exceptions', params] as const,
  exception: (exceptionId: string) => ['logistics', 'exception', exceptionId] as const,
}

export const useLogisticsExceptionListQuery = (params: LogisticsExceptionListParams) =>
  useQuery({ queryKey: logisticsQueryKeys.exceptions(params), queryFn: () => logisticsApi.listExceptions(params) })

export const useLogisticsExceptionQuery = (exceptionId: string | null) =>
  useQuery({
    queryKey: logisticsQueryKeys.exception(exceptionId ?? ''),
    queryFn: () => logisticsApi.getException(exceptionId ?? ''),
    enabled: Boolean(exceptionId),
  })

export function useLogisticsExceptionActionMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ action, values }: { action: string; values: LogisticsExceptionActionRequest }) => {
      const { exceptionId, versionId } = values
      if (action === 'claim') return logisticsApi.claimException(exceptionId, versionId)
      if (action === 'note') return logisticsApi.noteException(exceptionId, versionId, values.note ?? '')
      if (action === 'escalate')
        return logisticsApi.escalateException(exceptionId, versionId, values.severity ?? 'high', values.note ?? '')
      if (action === 'resolve') return logisticsApi.resolveException(exceptionId, versionId, values.resolution ?? '')
      return logisticsApi.closeException(exceptionId, versionId, values.note)
    },
    onSuccess: async (record) => {
      queryClient.setQueryData(logisticsQueryKeys.exception(record.id), record)
      await queryClient.invalidateQueries({ queryKey: ['logistics', 'exceptions'] })
    },
  })
}

export function useDetectLogisticsExceptionsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logisticsApi.detectExceptions,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['logistics', 'exceptions'] }),
  })
}

export function useSyncPlatformLogisticsMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logisticsApi.syncPlatformLogistics,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['logistics', 'exceptions'] })
      await queryClient.invalidateQueries({ queryKey: ['logistics', 'tasks'] })
    },
  })
}

export const useLogisticsTaskListQuery = (params: LogisticsTaskListParams) =>
  useQuery({ queryKey: logisticsQueryKeys.tasks(params), queryFn: () => logisticsApi.listTasks(params) })

export const useLogisticsTaskQuery = (taskId: string) =>
  useQuery({
    queryKey: logisticsQueryKeys.task(taskId),
    queryFn: () => logisticsApi.getTask(taskId),
    enabled: Boolean(taskId),
  })

export const useLogisticsPackagesQuery = (taskId: string) =>
  useQuery({
    queryKey: logisticsQueryKeys.packages(taskId),
    queryFn: () => logisticsApi.listPackages(taskId),
    enabled: Boolean(taskId),
  })

export const useLogisticsOrderContextQuery = (taskId: string, enabled: boolean) =>
  useQuery({
    queryKey: logisticsQueryKeys.orderContext(taskId),
    queryFn: () => logisticsApi.getOrderContext(taskId),
    enabled: Boolean(taskId) && enabled,
  })

export const useLogisticsShopOptionsQuery = () =>
  useQuery({ queryKey: logisticsQueryKeys.shops, queryFn: () => logisticsApi.listShops() })

export const useLogisticsCarriersQuery = () =>
  useQuery({ queryKey: logisticsQueryKeys.carriers, queryFn: () => logisticsApi.listCarriers() })

function useCarrierMasterMutation<T>(mutationFn: (data: T) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.carriers }),
  })
}

export const useCreateCarrierMutation = () =>
  useCarrierMasterMutation((data: LogisticsCarrierCreateRequest) => logisticsApi.createCarrier(data))

export const useCreateCarrierServiceMutation = (carrierId: string) =>
  useCarrierMasterMutation((data: LogisticsCarrierServiceCreateRequest) =>
    logisticsApi.createCarrierService(carrierId, data),
  )

export const useCreatePlatformCarrierMappingMutation = (carrierId: string) =>
  useCarrierMasterMutation((data: LogisticsPlatformCarrierMappingCreateRequest) =>
    logisticsApi.createPlatformCarrierMapping(carrierId, data),
  )

export const useUpdatePlatformCarrierMappingMutation = () =>
  useCarrierMasterMutation(
    ({ mappingId, data }: { mappingId: string; data: LogisticsPlatformCarrierMappingUpdateRequest }) =>
      logisticsApi.updatePlatformCarrierMapping(mappingId, data),
  )

export const useLogisticsWaybillsQuery = (packageId: string) =>
  useQuery({
    queryKey: logisticsQueryKeys.waybills(packageId),
    queryFn: () => logisticsApi.listWaybills(packageId),
    enabled: Boolean(packageId),
  })

export function useReviewTaskMutation(taskId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: LogisticsReviewRequest) => logisticsApi.reviewTask(taskId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useConfirmPickingMutation(taskId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => logisticsApi.confirmPicking(taskId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useCreatePackageMutation(taskId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: LogisticsPackageDraftCreateRequest) => logisticsApi.createPackageDraft(taskId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useUpdatePackageMutation(taskId: string, packageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: LogisticsPackageDraftUpdateRequest) => logisticsApi.updatePackageDraft(packageId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
    },
  })
}

export function useSealPackageMutation(taskId: string, packageId: string, sealed: boolean) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (versionId: number) =>
      sealed ? logisticsApi.unsealPackage(packageId, versionId) : logisticsApi.sealPackage(packageId, versionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useShippingQuoteMutation(packageId: string) {
  return useMutation({ mutationFn: () => logisticsApi.quoteShipping(packageId) })
}

export function useCreateWaybillMutation(taskId: string, packageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: LogisticsWaybillCreateRequest) => logisticsApi.createWaybill(packageId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.waybills(packageId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useCancelWaybillMutation(taskId: string, packageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ waybillId, versionId, reason }: { waybillId: string; versionId: number; reason: string }) =>
      logisticsApi.cancelWaybill(waybillId, versionId, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.waybills(packageId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}

export function useUploadWaybillLabelMutation(packageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ waybillId, file }: { waybillId: string; file: File }) =>
      logisticsApi.uploadWaybillLabel(waybillId, file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.waybills(packageId) })
    },
  })
}

export function useDispatchPackageMutation(taskId: string, packageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: LogisticsPackageDispatchRequest) => logisticsApi.dispatchPackage(packageId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.task(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.packages(taskId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.waybills(packageId) })
      await queryClient.invalidateQueries({ queryKey: logisticsQueryKeys.all })
    },
  })
}
