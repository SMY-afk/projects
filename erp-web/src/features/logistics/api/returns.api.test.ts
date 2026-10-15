import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReturnRequestCreate } from '../types/returns.types'

const mocks = vi.hoisted(() => ({ request: vi.fn() }))

vi.mock('@/services/http-client', () => mocks)

describe('returns API contract', () => {
  afterEach(() => mocks.request.mockReset())

  it('checks eligibility by original order reference', async () => {
    mocks.request.mockResolvedValue({ items: [] })
    const { returnsApi } = await import('./returns.api')
    await returnsApi.getEligibility('ORDER-1')
    expect(mocks.request).toHaveBeenCalledWith({
      method: 'get',
      url: '/returns/eligibility',
      params: { orderReference: 'ORDER-1' },
    })
  })

  it('passes all return center filters to the list endpoint', async () => {
    mocks.request.mockResolvedValue({ items: [], total: 0 })
    const { returnsApi } = await import('./returns.api')
    const params = {
      page: 1,
      pageSize: 20,
      shopId: 'shop-1',
      requestType: 'return' as const,
      status: 'approved' as const,
      reason: 'damaged',
      appliedFrom: '2026-08-01T00:00:00.000Z',
      appliedTo: '2026-08-25T23:59:59.999Z',
      rma: 'RMA-20260825',
    }
    await returnsApi.list(params)
    expect(mocks.request).toHaveBeenCalledWith({ method: 'get', url: '/returns/requests', params })
  })

  it('loads a return request detail by id', async () => {
    mocks.request.mockResolvedValue({})
    const { returnsApi } = await import('./returns.api')
    await returnsApi.get('return-1')
    expect(mocks.request).toHaveBeenCalledWith({ method: 'get', url: '/returns/return-1' })
  })

  it('submits only original order lines and requested quantities', async () => {
    mocks.request.mockResolvedValue({})
    const { returnsApi } = await import('./returns.api')
    const data: ReturnRequestCreate = {
      orderId: 'order-1',
      requestType: 'return',
      reasonCode: 'damaged',
      customerNote: null,
      items: [
        {
          orderLineId: 'line-1',
          requestedQuantity: 1,
          reasonCode: 'damaged',
          note: null,
        },
      ],
    }
    await returnsApi.create(data)
    expect(mocks.request).toHaveBeenCalledWith({ method: 'post', url: '/returns', data })
  })

  it('reviews with optimistic lock and no waybill fields', async () => {
    mocks.request.mockResolvedValue({})
    const { returnsApi } = await import('./returns.api')
    const data = { decision: 'approve' as const, versionId: 3, note: null }
    await returnsApi.review('return-1', data)
    expect(mocks.request).toHaveBeenCalledWith({
      method: 'post',
      url: '/returns/return-1/review',
      data,
    })
    expect(JSON.stringify(data)).not.toMatch(/tracking|waybill/i)
  })

  it('syncs real platform returns for the selected shop', async () => {
    mocks.request.mockResolvedValue({})
    const { returnsApi } = await import('./returns.api')
    await returnsApi.sync('shop-1')
    expect(mocks.request).toHaveBeenCalledWith({
      method: 'post',
      url: '/returns/sync',
      data: { shopId: 'shop-1' },
    })
  })
})
