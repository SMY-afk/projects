import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useShopLocalToday } from './use-shop-local-today'

describe('useShopLocalToday', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-01T06:59:00.000Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('refreshes at the next shop-local day boundary while the page remains open', async () => {
    const { result } = renderHook(() => useShopLocalToday('America/Los_Angeles'))

    expect(result.current.format('YYYY-MM-DD')).toBe('2026-08-31')

    await act(() => Promise.resolve(vi.advanceTimersByTime(60_001)))

    expect(result.current.format('YYYY-MM-DD')).toBe('2026-09-01')
  })
})
