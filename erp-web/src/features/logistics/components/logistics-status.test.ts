import { describe, expect, it } from 'vitest'
import { LOGISTICS_STATUS_STEPS, getLogisticsStatusPresentation } from './logistics-status'

describe('logistics workflow status contract', () => {
  it('keeps the eight agreed labels in a stable order', () => {
    expect(LOGISTICS_STATUS_STEPS.map((item) => item.title)).toEqual([
      '待复核',
      '待打包',
      '待运单',
      '待发货',
      '已发货',
      '运输中',
      '已签收',
      '异常',
    ])
  })

  it('maps the normal workflow to progressive step indexes', () => {
    expect(getLogisticsStatusPresentation('pending_review')).toMatchObject({ current: 0, stepStatus: 'process' })
    expect(getLogisticsStatusPresentation('pending_dispatch')).toMatchObject({ current: 3, stepStatus: 'process' })
    expect(getLogisticsStatusPresentation('delivered')).toMatchObject({ current: 6, stepStatus: 'finish' })
  })

  it('renders exception as an explicit error branch', () => {
    expect(getLogisticsStatusPresentation('exception')).toEqual({
      current: 7,
      label: '异常',
      stepStatus: 'error',
    })
  })
})
