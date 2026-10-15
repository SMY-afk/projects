import type { ReturnRequestRecord } from '../types/returns.types'

export const returnFlowSteps = ['申请', '审核', '退回', '收货', '质检', '入库/换货/退款']

export interface ReturnFlowState {
  current: number
  status: 'process' | 'finish' | 'error'
  basis: string
}

export function getReturnFlowState(record: ReturnRequestRecord): ReturnFlowState {
  const platformStatus = (record.platformStatus ?? '').toUpperCase()
  if (record.status === 'rejected' || record.status === 'cancelled') {
    return { current: 1, status: 'error', basis: '申请已拒绝或取消' }
  }
  if (platformStatus.includes('COMPLETE') || record.rma?.status === 'closed') {
    return { current: 5, status: 'finish', basis: '平台或 RMA 已报告流程完成' }
  }
  if (record.rma?.status === 'received') {
    return { current: 4, status: 'process', basis: 'RMA 已收货，等待质检及最终处置' }
  }
  if (
    record.rma?.status === 'in_transit' ||
    platformStatus.includes('BUYER_SHIPPED') ||
    platformStatus.includes('IN_TRANSIT')
  ) {
    return { current: 2, status: 'process', basis: '退回包裹运输中' }
  }
  if (record.status === 'approved' || record.rma || platformStatus.includes('AWAITING_BUYER_SHIP')) {
    return { current: 2, status: 'process', basis: '审核已通过，等待买家退回' }
  }
  return { current: 1, status: 'process', basis: '申请已创建，等待审核' }
}
