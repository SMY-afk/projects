import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useAffiliateDateWindow } from './use-affiliate-date-window'

const filters = { shopId: 'shop-1', from: '2026-10-06', to: '2026-10-12', currency: 'USD' }
const scope = 'shopId=shop-1&currency=USD&videoFrom=2026-10-06&videoTo=2026-10-12'

describe('useAffiliateDateWindow', () => {
  it('preserves fixed dates while the final source day is unavailable', () => {
    const write = vi.fn()
    renderHook(() => useAffiliateDateWindow(filters, '2026-10-11', `${scope}&videoRolling=fixed`, 'videos', write))
    expect(write).not.toHaveBeenCalled()
  })

  it('does not turn a fixed seven-day window into a rolling window', () => {
    const write = vi.fn()
    renderHook(() => useAffiliateDateWindow(filters, '2026-10-12', `${scope}&videoRolling=fixed`, 'videos', write))
    expect(write).not.toHaveBeenCalled()
  })

  it('continues moving explicitly rolling dates to the latest available day', () => {
    const write = vi.fn()
    renderHook(() => useAffiliateDateWindow(filters, '2026-10-11', `${scope}&videoRolling=last7d`, 'videos', write))
    expect(write).toHaveBeenCalledWith({ ...filters, from: '2026-10-05', to: '2026-10-11' }, true, 'last7d')
  })
})
