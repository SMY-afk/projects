import { Button, Modal, Progress, Typography, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { logisticsStatusApi } from '../api/logistics-status.api'
import type { LogisticsAlertPhase, LogisticsOrderAlert, LogisticsStatusOrder } from '../types/logistics-status.types'
import { queryLiveExport, type ExportProgress } from '../utils/logistics-status-live-export'
import type { LogisticsOrderCategory } from '../utils/logistics-order-categories'
import { request } from '@/services/http-client'

export function LogisticsStatusExportButton({
  shopId,
  shopName,
  orderNumber,
  order,
  disabled,
  category,
  alert,
  alertPhase,
}: {
  shopId?: string
  shopName?: string
  orderNumber?: string
  order?: LogisticsStatusOrder
  disabled?: boolean
  category?: LogisticsOrderCategory
  alert?: LogisticsOrderAlert
  alertPhase?: LogisticsAlertPhase
}) {
  const [exporting, setExporting] = useState(false)
  const [progress, setProgress] = useState<ExportProgress>({ completed: 0, total: 0, failed: 0 })
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const exportExcel = async () => {
    const active = new AbortController()
    controller.current = active
    setExporting(true)
    setProgress({ completed: 0, total: 0, failed: 0 })
    try {
      const data = order
        ? { items: [order], total: 1 }
        : await logisticsStatusApi.exportOrders({ shopId, orderNumber, category, alert, alertPhase }, active.signal)
      if (data.items.length !== data.total) throw new Error('Incomplete export')
      if (!data.total) {
        void message.info('当前筛选下没有可导出的订单')
        return
      }
      const shops = await request<{ id: string; timezone: string | null }[]>({ method: 'get', url: '/shops', signal: active.signal })
      const timezones = Object.fromEntries(shops.map((shop) => [shop.id, shop.timezone]))
      for (const item of data.items) {
        const timezone = timezones[item.shopId]
        if (!timezone) throw new Error('Missing shop timezone')
        new Intl.DateTimeFormat('en-US', { timeZone: timezone }).format()
      }
      active.signal.throwIfAborted()
      const { liveByOrder, failures } = await queryLiveExport(
        data.items,
        logisticsStatusApi.refresh,
        active.signal,
        setProgress,
      )
      if (!Object.keys(liveByOrder).length) throw new Error('All official queries failed')
      const { buildLogisticsStatusExcel, saveLogisticsStatusExcel } = await import('../utils/logistics-status-export')
      const result = await buildLogisticsStatusExcel(
        data.items,
        liveByOrder,
        order
          ? order.orderNumber
          : `${shopName ?? (shopId ? '所选店铺' : '全部店铺')}${orderNumber ? ` · 订单${orderNumber}` : ''}`,
        failures,
        timezones,
      )
      active.signal.throwIfAborted()
      saveLogisticsStatusExcel(result.blob, result.fileName)
      if (Object.keys(failures).length)
        void message.warning(`已导出 ${data.total} 个订单，其中 ${Object.keys(failures).length} 单查询失败，表内已标明`)
      else void message.success(`已实时查询并导出 ${data.total} 个订单`)
    } catch {
      if (active.signal.aborted) void message.info('已取消导出')
      else void message.error('实时 Excel 导出失败，请重试或检查店铺授权')
    } finally {
      setExporting(false)
    }
  }
  return (
    <>
      <Button loading={exporting} disabled={disabled} onClick={() => void exportExcel()}>
        {order ? '导出本单 Excel' : '导出 Excel（当前筛选全部订单）'}
      </Button>
      <Modal
        title="实时查询后导出 Excel"
        open={exporting}
        footer={<Button onClick={() => controller.current?.abort()}>取消导出</Button>}
        closable={false}
        maskClosable={false}
      >
        <Typography.Paragraph>
          逐单读取官方当前订单状态和物流轨迹。订单较多时耗时较长，请保持页面打开。
        </Typography.Paragraph>
        <Progress percent={progress.total ? Math.floor((progress.completed / progress.total) * 100) : 0} />
        <Typography.Text>
          已查询 {progress.completed} / {progress.total} 单，失败 {progress.failed} 单
        </Typography.Text>
      </Modal>
    </>
  )
}
