import type {
  LogisticsExceptionSeverity,
  LogisticsExceptionStatus,
  LogisticsExceptionType,
} from '../types/logistics-exception.types'

export const exceptionTypeLabels: Record<LogisticsExceptionType, string> = {
  not_picked_up: '未揽收',
  stalled: '运输滞留',
  address_error: '地址错误',
  refused: '拒收',
  lost: '丢失',
  damaged: '破损',
  platform_status_mismatch: '平台状态不一致',
}

export const exceptionStatusPresentation: Record<LogisticsExceptionStatus, { label: string; color: string }> = {
  open: { label: '待认领', color: 'red' },
  claimed: { label: '处理中', color: 'blue' },
  escalated: { label: '已升级', color: 'volcano' },
  resolved: { label: '已解决', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
}

export const exceptionSeverityPresentation: Record<LogisticsExceptionSeverity, { label: string; color: string }> = {
  low: { label: '低', color: 'default' },
  medium: { label: '中', color: 'orange' },
  high: { label: '高', color: 'volcano' },
  critical: { label: '紧急', color: 'red' },
}

export const exceptionActionLabels: Record<string, string> = {
  detected: '系统识别',
  claimed: '认领异常',
  note_added: '添加备注',
  escalated: '升级异常',
  resolved: '解决异常',
  closed: '关闭异常',
}
