import { describe, expect, it } from 'vitest'
import { elapsedSince, orderElapsed } from './logistics-order-categories'

describe('order elapsed time', () => {
  it('freezes delivered duration at the official delivered event across different current times', () => {
    const order = {
      orderCreatedAt: '2026-10-07T08:52:41Z',
      platformStatus: 'COMPLETED',
      deliveredAt: '2026-10-10T17:04:00Z',
    }
    expect(orderElapsed(order, Date.parse('2026-10-12T00:00:00Z'))).toBe('3天 8小时 11分钟')
    expect(orderElapsed(order, Date.parse('2026-10-22T00:00:00Z'))).toBe('3天 8小时 11分钟')
  })
  it('does not substitute the query time when a delivered order has no delivery event', () => {
    expect(orderElapsed({ orderCreatedAt: '2026-10-07T08:52:41Z', platformStatus: 'DELIVERED' }, Date.now())).toBe(
      '送达时间待查询',
    )
  })
  it('uses creation time across time zones with days, hours and minutes', () => {
    expect(elapsedSince('2026-10-10T08:00:00Z', Date.parse('2026-10-12T17:31:00+08:00'))).toBe('2天 1小时 31分钟')
  })
  it('shows invalid or future creation times instead of a plausible zero', () => {
    expect(elapsedSince('invalid', Date.now())).toBe('订单时间异常')
    expect(elapsedSince('2027-01-01T00:00:00Z', Date.parse('2026-10-12T00:00:00Z'))).toBe('订单时间异常')
  })
})
