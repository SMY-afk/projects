import { App } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { logisticsApi } from '../api/logistics.api'
import {
  useCancelWaybillMutation,
  useCreateWaybillMutation,
  useDispatchPackageMutation,
  useLogisticsCarriersQuery,
  useLogisticsWaybillsQuery,
  useShippingQuoteMutation,
  useUploadWaybillLabelMutation,
} from '../queries/logistics.queries'
import type {
  LogisticsPackage,
  LogisticsShippingQuote,
  LogisticsTaskItem,
  LogisticsWaybillCreateRequest,
} from '../types/logistics.types'
import { LogisticsDispatchModal } from './logistics-dispatch-modal'
import { LogisticsServiceDrawer } from './logistics-service-drawer'
import { LogisticsWaybillPanel, type ManualWaybillFields } from './logistics-waybill-panel'

interface LogisticsShippingPanelProps {
  taskId: string
  packageItem: LogisticsPackage
  taskItems: LogisticsTaskItem[]
}

export function LogisticsShippingPanel({ taskId, packageItem, taskItems }: LogisticsShippingPanelProps) {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const quoteMutation = useShippingQuoteMutation(packageItem.id)
  const createMutation = useCreateWaybillMutation(taskId, packageItem.id)
  const cancelMutation = useCancelWaybillMutation(taskId, packageItem.id)
  const labelMutation = useUploadWaybillLabelMutation(packageItem.id)
  const dispatchMutation = useDispatchPackageMutation(taskId, packageItem.id)
  const waybillsQuery = useLogisticsWaybillsQuery(packageItem.id)
  const carriersQuery = useLogisticsCarriersQuery()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [dispatchOpen, setDispatchOpen] = useState(false)
  const [selectedQuote, setSelectedQuote] = useState<LogisticsShippingQuote | null>(null)
  const [draftQuote, setDraftQuote] = useState<LogisticsShippingQuote | null>(null)
  const currentWaybill = waybillsQuery.data?.find((item) => item.isCurrent)
  const carriers = carriersQuery.data ?? []
  const selectedCarrier = carriers.find((item) => item.id === selectedQuote?.carrierId)
  const currentCarrier = carriers.find((item) => item.id === currentWaybill?.carrierId)
  const currentService = currentCarrier?.services.find((item) => item.id === currentWaybill?.serviceId)
  const quotes = quoteMutation.data ?? []

  const packageTotal = useMemo(
    () => packageItem.items.reduce((total, item) => total + item.quantity, 0),
    [packageItem.items],
  )

  const quote = async () => {
    try {
      const records = await quoteMutation.mutateAsync()
      if (!records.length) void message.warning('没有可用物流服务')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '运费试算失败')
    }
  }

  const chooseService = () => {
    setDraftQuote(selectedQuote)
    setDrawerOpen(true)
    if (!quotes.length) void quote()
  }

  const createWaybill = async (data: LogisticsWaybillCreateRequest, successMessage: string) => {
    if (!selectedQuote) return void message.warning('请先选择物流服务')
    try {
      await createMutation.mutateAsync(data)
      void message.success(successMessage)
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '创建运单失败')
    }
  }

  const createManual = (values: ManualWaybillFields) => {
    if (!selectedQuote) return
    void createWaybill(
      {
        carrierId: selectedQuote.carrierId,
        serviceId: selectedQuote.serviceId,
        accountId: selectedQuote.accountId,
        trackingNumber: values.trackingNumber.trim(),
        externalWaybillId: values.externalWaybillId?.trim() || null,
      },
      '人工运单已创建',
    )
  }

  const createOnline = () => {
    if (!selectedQuote) return
    void createWaybill(
      {
        carrierId: selectedQuote.carrierId,
        serviceId: selectedQuote.serviceId,
        accountId: selectedQuote.accountId,
        trackingNumber: null,
        externalWaybillId: null,
      },
      '在线运单已创建',
    )
  }

  const cancelWaybill = async () => {
    if (!currentWaybill) return
    try {
      await cancelMutation.mutateAsync({
        waybillId: currentWaybill.id,
        versionId: currentWaybill.versionId,
        reason: '人工取消运单',
      })
      void message.success('运单已取消，包裹退回待运单')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '取消运单失败')
    }
  }

  const getLabel = async (mode: 'download' | 'print') => {
    if (!currentWaybill) return
    try {
      const label = await logisticsApi.getWaybillLabel(currentWaybill.id)
      if (mode === 'print') {
        window.open(label.downloadUrl, '_blank', 'noopener,noreferrer')
        return
      }
      const anchor = document.createElement('a')
      anchor.href = label.downloadUrl
      anchor.download = label.originalFilename
      anchor.rel = 'noopener noreferrer'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '面单暂不可用')
    }
  }

  const uploadLabel = async (file?: File) => {
    if (!currentWaybill || !file) return
    try {
      await labelMutation.mutateAsync({ waybillId: currentWaybill.id, file })
      void message.success('面单已保存到对象存储')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '面单上传失败')
    }
  }

  const dispatch = async () => {
    if (!currentWaybill) return
    try {
      await dispatchMutation.mutateAsync({
        packageVersionId: packageItem.versionId,
        waybillId: currentWaybill.id,
        waybillVersionId: currentWaybill.versionId,
        items: packageItem.items.map((item) => ({ taskItemId: item.taskItemId, quantity: item.quantity })),
        note: null,
      })
      setDispatchOpen(false)
      void message.success(`${packageItem.packageNumber} 已发货，共 ${packageTotal} 件`)
      void navigate(`/logistics/tasks/${taskId}`)
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '确认发货失败')
    }
  }

  return (
    <>
      <LogisticsWaybillPanel
        cancelling={cancelMutation.isPending}
        creating={createMutation.isPending}
        currentCarrier={currentCarrier}
        currentService={currentService}
        currentWaybill={currentWaybill}
        onCancelWaybill={() => void cancelWaybill()}
        onChooseService={chooseService}
        onCreateManual={createManual}
        onCreateOnline={createOnline}
        onDownloadLabel={() => void getLabel('download')}
        onOpenDispatch={() => setDispatchOpen(true)}
        onReprintLabel={() => void getLabel('print')}
        onUploadLabel={(file) => void uploadLabel(file)}
        selectedCarrier={selectedCarrier}
        selectedQuote={selectedQuote}
        uploading={labelMutation.isPending}
      />
      <LogisticsServiceDrawer
        loading={quoteMutation.isPending}
        onClose={() => setDrawerOpen(false)}
        onConfirm={() => {
          setSelectedQuote(draftQuote)
          setDrawerOpen(false)
        }}
        onRefresh={() => void quote()}
        onSelect={setDraftQuote}
        open={drawerOpen}
        quotes={quotes}
        selected={draftQuote}
      />
      {currentWaybill && (
        <LogisticsDispatchModal
          carrier={currentCarrier}
          loading={dispatchMutation.isPending}
          onCancel={() => setDispatchOpen(false)}
          onConfirm={() => void dispatch()}
          open={dispatchOpen}
          packageItem={packageItem}
          service={currentService}
          taskItems={taskItems}
          waybill={currentWaybill}
        />
      )}
    </>
  )
}
