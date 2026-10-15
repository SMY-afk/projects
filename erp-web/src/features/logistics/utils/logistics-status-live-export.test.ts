import { describe, expect, it, vi } from 'vitest'
import { queryLiveExport } from './logistics-status-live-export'
import { liveFixture } from './logistics-status-test-fixture'
import type { LogisticsStatusOrder } from '../types/logistics-status.types'

describe('official live export queries', () => {
  it('queries every order with bounded concurrency and reports failed rows without cache', async () => {
    const orders = Array.from({ length: 8 }, (_, index) => ({ id: String(index) }) as LogisticsStatusOrder)
    let active = 0
    let maximum = 0
    const refresh = vi.fn(async (id: string) => {
      active += 1
      maximum = Math.max(maximum, active)
      await new Promise((resolve) => setTimeout(resolve, 1))
      active -= 1
      if (id === '2') throw new Error('Official query failed')
      return { ...liveFixture, orderId: id }
    })
    const progress = vi.fn()
    const result = await queryLiveExport(orders, refresh, new AbortController().signal, progress)
    expect(refresh).toHaveBeenCalledTimes(8)
    expect(maximum).toBeLessThanOrEqual(3)
    expect(Object.keys(result.liveByOrder)).toHaveLength(7)
    expect(result.liveByOrder['2']).toBeUndefined()
    expect(result.failures['2']).toContain('查询失败')
    expect(progress).toHaveBeenLastCalledWith({ completed: 8, total: 8, failed: 1 })
  })

  it('cancels before querying or exporting an incomplete collection', async () => {
    const controller = new AbortController()
    controller.abort()
    const refresh = vi.fn()
    await expect(
      queryLiveExport([{ id: 'one' } as LogisticsStatusOrder], refresh, controller.signal, vi.fn()),
    ).rejects.toThrow()
    expect(refresh).not.toHaveBeenCalled()
  })
})
