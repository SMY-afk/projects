import { describe, expect, it } from 'vitest'
import { getReturnFlowState, returnFlowSteps } from './return-flow'
import type { ReturnRequestRecord } from '../types/returns.types'

const record = (values: Partial<ReturnRequestRecord> = {}) =>
  ({
    status: 'pending_review',
    platformStatus: null,
    rma: null,
    ...values,
  }) as ReturnRequestRecord

describe('return detail flow', () => {
  it('uses the approved six-stage business language', () => {
    expect(returnFlowSteps).toEqual(['申请', '审核', '退回', '收货', '质检', '入库/换货/退款'])
  })

  it('maps review, reverse shipping, receipt and completion without inventory writes', () => {
    expect(getReturnFlowState(record()).current).toBe(1)
    expect(
      getReturnFlowState(record({ status: 'approved', rma: { status: 'in_transit' } as ReturnRequestRecord['rma'] }))
        .current,
    ).toBe(2)
    expect(
      getReturnFlowState(record({ status: 'approved', rma: { status: 'received' } as ReturnRequestRecord['rma'] }))
        .current,
    ).toBe(4)
    expect(getReturnFlowState(record({ platformStatus: 'RETURN_OR_REFUND_REQUEST_COMPLETE' })).current).toBe(5)
  })

  it('marks rejected and cancelled applications as failed review flows', () => {
    expect(getReturnFlowState(record({ status: 'rejected' })).status).toBe('error')
    expect(getReturnFlowState(record({ status: 'cancelled' })).status).toBe('error')
  })
})
