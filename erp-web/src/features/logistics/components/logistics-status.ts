import type { LogisticsTaskStatus } from '../types/logistics.types'

export const LOGISTICS_STATUS_STEPS = [
  { key: 'pending_review', title: '待复核' },
  { key: 'pending_pack', title: '待打包' },
  { key: 'pending_waybill', title: '待运单' },
  { key: 'pending_dispatch', title: '待发货' },
  { key: 'shipped', title: '已发货' },
  { key: 'in_transit', title: '运输中' },
  { key: 'delivered', title: '已签收' },
  { key: 'exception', title: '异常' },
] as const

type StepStatus = 'wait' | 'process' | 'finish' | 'error'

interface StatusPresentation {
  current: number
  label: string
  stepStatus: StepStatus
}

const statusIndex = Object.fromEntries(LOGISTICS_STATUS_STEPS.map((item, index) => [item.key, index])) as Record<
  Exclude<LogisticsTaskStatus, 'cancelled'>,
  number
>

export function getLogisticsStatusPresentation(status: LogisticsTaskStatus): StatusPresentation {
  if (status === 'cancelled') return { current: 0, label: '已取消', stepStatus: 'error' }
  const current = statusIndex[status]
  return {
    current,
    label: LOGISTICS_STATUS_STEPS[current].title,
    stepStatus: status === 'exception' ? 'error' : status === 'delivered' ? 'finish' : 'process',
  }
}
