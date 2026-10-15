import type { LogisticsStatusLive, LogisticsStatusOrder } from '../types/logistics-status.types'
import type { Sheet, Row, Cell } from 'write-excel-file/universal'
import { shippingMethodLabel } from './logistics-shipping-method'
import { firstPackedEvent, localExcelDate, timezoneHourCorrection } from './logistics-export-time'
import { translateTrackingDescription } from './logistics-tracking-translation'

const labels: Record<string, string> = {
  AWAITING_SHIPMENT: '待发货',
  AWAITING_COLLECTION: '待揽收',
  PARTIALLY_SHIPPING: '部分发货',
  IN_TRANSIT: '运输中',
  DELIVERED: '已送达',
  COMPLETED: '已完成',
  order_created: '订单已创建',
  ready_for_collection: '已打包待揽收',
  info_received: '已收到物流信息',
  picked_up: '已揽收',
  in_transit: '运输中',
  out_for_delivery: '派送中',
  delivered: '已送达',
  exception: '物流异常',
  returned: '已退回',
  cancelled: '已取消',
}
const label = (value: string) => labels[value] ?? value
const text = (value: string): Cell => ({ value, type: String, format: '@', wrap: true, alignVertical: 'top' })
const date = (value?: string | null, timezone = 'Asia/Shanghai'): Cell =>
  value
    ? {
        value: localExcelDate(value, timezone),
        type: Date,
        format: 'yyyy-mm-dd hh:mm:ss',
        alignVertical: 'top',
      }
    : null
const duration = (start: string, end: string, row: number, correction: number): Cell => ({
  type: 'Formula',
  value: `IF(AND(ISNUMBER(${start}${row}),ISNUMBER(${end}${row})),(${end}${row}-${start}${row})*24${correction ? `${correction > 0 ? '+' : ''}${correction}` : ''},"")`,
  format: '0.000000',
})
const headers = [
  '店铺',
  '订单号',
  '实时订单状态',
  '实时物流状态',
  '订单创建时间（当地时间）',
  '当地时间的发货时间',
  '当地时间的真实发货时间',
  '实际送达时间（当地时间）',
  '创建至发货（小时）',
  '发货至真实发货（小时）',
  '首次地点轨迹依据',
  '最新轨迹',
  '发货轨迹依据',
  '送达轨迹依据',
  '官方查询时间（北京时间）',
  '订单数据同步时间（北京时间）',
  '包裹号',
  '包裹状态',
  '承运商',
  '运单号（脱敏）',
  '核对说明',
  '导出时间（北京时间）',
  '物流方式',
]

export async function buildLogisticsStatusExcel(
  orders: LogisticsStatusOrder[],
  liveByOrder: Record<string, LogisticsStatusLive>,
  scope: string,
  failures: Record<string, string> = {},
  shopTimezones: Record<string, string | null> = {},
) {
  const { default: writeExcelFile } = await import('write-excel-file/universal')
  const exportedAt = new Date().toISOString()
  const data: Row[] = [
    [
      {
        value: `物流状态 · ${scope} · ${orders.length} 个订单`,
        columnSpan: headers.length,
        fontWeight: 'bold',
        height: 28,
      },
    ],
    [
      {
        value: '每单均在本次导出时查询官方数据；节点及轨迹时间按店铺当地时区显示，时区见核对说明。官方查询、ERP同步及导出时间为北京时间。轨迹描述由ERP翻译，地名保留原文；未匹配的特殊轨迹保留官方原文。',
        columnSpan: headers.length,
      },
    ],
    [
      {
        value:
          '创建取ERP全部订单的下单时间；发货取首次订单已打包、等待承运商揽收；真实发货取轨迹首次具体地址；送达取实际已送达。创建至发货=发货减创建；发货至真实发货按指定口径=真实发货减创建。单位小时，跨夏令时按实际经过时长计算；未完成节点留空。',
        columnSpan: headers.length,
        wrap: true,
        height: 32,
      },
    ],
    headers.map((value) => ({
      value,
      fontWeight: 'bold',
      textColor: '#ffffff',
      backgroundColor: '#087f78',
      wrap: true,
      height: 36,
    })),
  ]
  for (const order of orders) {
    const live = liveByOrder[order.id]
    if (!live && !failures[order.id]) throw new Error('A fresh official result is required for every exported order')
    const timezone = shopTimezones[order.shopId]
    if (!timezone) throw new Error('A valid shop timezone is required for local timestamps')
    const createdAt = live?.orderCreatedAt ?? order.orderCreatedAt
    const latest = [...(live?.events ?? [])]
      .filter((event) => Number.isFinite(Date.parse(event.occurredAt)))
      .sort((a, b) => Date.parse(b.occurredAt) - Date.parse(a.occurredAt))[0]
    const packed = firstPackedEvent(live)
    const packages = live?.packages ?? []
    const row = data.length + 1
    data.push([
      text(order.shopName),
      text(order.orderNumber),
      text(live ? label(live.platformStatus) : '查询失败'),
      text(live ? (live.trackingStatus ? label(live.trackingStatus) : '官方暂无轨迹') : '查询失败'),
      date(createdAt, timezone),
      date(packed?.occurredAt, timezone),
      date(live?.firstLocationAt, timezone),
      date(live?.deliveredAt, timezone),
      duration('E', 'F', row, timezoneHourCorrection(createdAt, packed?.occurredAt ?? null, timezone)),
      duration('E', 'G', row, timezoneHourCorrection(createdAt, live?.firstLocationAt ?? null, timezone)),
      text(translateTrackingDescription(live?.firstLocationDescription)),
      text(latest ? (translateTrackingDescription(latest.description).trim() || label(latest.status)) : ''),
      text(translateTrackingDescription(packed?.description)),
      text(translateTrackingDescription(live?.deliveredDescription)),
      date(live?.checkedAt),
      date(live?.erpSyncedAt ?? order.erpSyncedAt),
      text(packages.map((item) => item.packageId).join('\n')),
      text(packages.map((item) => label(item.packageStatus)).join('\n')),
      text(packages.map((item) => item.carrierName ?? '承运商未知').join('\n')),
      text(packages.map((item) => item.trackingNumberMasked ?? '').join('\n')),
      text(`店铺时区：${timezone}；${live ? [...live.milestoneNotes, ...(!packed ? ['官方轨迹暂无已打包待揽收事件'] : [])].join('；') : failures[order.id]}`),
      date(exportedAt),
      text(shippingMethodLabel(live ? live.shippingType : order.shippingType,
        live ? live.fulfillmentType : order.fulfillmentType)),
    ])
  }
  const sheets: Sheet<Blob>[] = [
    {
      data,
      sheet: '物流状态',
      stickyRowsCount: 4,
      stickyColumnsCount: 2,
      columns: [24, 26, 16, 20, 28, 28, 30, 28, 22, 24, 65, 65, 48, 48, 24, 26, 36, 22, 24, 28, 52, 24, 20].map(
        (width) => ({ width }),
      ),
    },
  ]
  const events: Row[] = [
    ['店铺', '订单号', '官方查询时间（北京时间）', '轨迹发生时间（当地时间）', '轨迹状态', '事件代码', '轨迹描述', '店铺时区'].map(
      (value) => ({ value, fontWeight: 'bold', wrap: true, height: 34 }),
    ),
  ]
  for (const order of orders) {
    const live = liveByOrder[order.id]
    for (const event of live?.events ?? []) {
      events.push([
        text(order.shopName),
        text(order.orderNumber),
        date(live.checkedAt),
        date(event.occurredAt, shopTimezones[order.shopId]!),
        text(label(event.status)),
        text(event.actionCode),
        text(translateTrackingDescription(event.description)),
        text(shopTimezones[order.shopId]!),
      ])
    }
  }
  sheets.push({
    data: events,
    sheet: '官方实时轨迹',
    stickyRowsCount: 1,
    stickyColumnsCount: 2,
    columns: [24, 26, 24, 28, 22, 16, 80, 26].map((width) => ({ width })),
  })
  const blob = await writeExcelFile(sheets).toBlob()
  return {
    blob,
    fileName: `物流状态_${scope.replace(/[\\/:*?"<>|]/g, '_')}_${exportedAt.slice(0, 19).replace(/[-:T]/g, '')}.xlsx`,
  }
}

export function saveLogisticsStatusExcel(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
