import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ downloadFile: vi.fn(), request: vi.fn() }))

vi.mock('@/services/http-client', () => mocks)

async function loadFinanceApi() {
  vi.resetModules()
  return import('./finance.api')
}

describe('Finance API boundary', () => {
  afterEach(() => {
    mocks.request.mockReset()
    mocks.downloadFile.mockReset()
    vi.unstubAllEnvs()
  })

  it('uses HTTP unless the dedicated Finance Mock flag is explicitly true', async () => {
    vi.stubEnv('VITE_USE_MOCK', 'true')
    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'false')
    mocks.request.mockResolvedValue({ items: [] })
    const { financeApi, isFinanceMock } = await loadFinanceApi()

    await financeApi.overview({ shopId: 'shop-1', from: '2026-08-01T00:00:00Z', to: '2026-08-21T00:00:00Z' })

    expect(isFinanceMock).toBe(false)
    expect(mocks.request).toHaveBeenCalledWith({
      method: 'get',
      url: '/finance/overview',
      params: { shopId: 'shop-1', from: '2026-08-01T00:00:00Z', to: '2026-08-21T00:00:00Z' },
    })
  })

  it('keeps a real API failure visible instead of falling back to Finance fixtures', async () => {
    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'false')
    mocks.request.mockRejectedValue(new Error('finance backend unavailable'))
    const { financeApi, isFinanceMock } = await loadFinanceApi()

    await expect(financeApi.statements({ page: 1, pageSize: 20, currency: 'USD' })).rejects.toThrow(
      'finance backend unavailable',
    )
    expect(isFinanceMock).toBe(false)
  })

  it('sends list, detail, reconciliation, export and sync contracts unchanged', async () => {
    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'false')
    mocks.request.mockResolvedValue({})
    mocks.downloadFile.mockResolvedValue({ blob: new Blob() })
    const { financeApi } = await loadFinanceApi()
    const transactionParams = {
      page: 2,
      pageSize: 50,
      shopId: 'shop-1',
      statementId: 'statement-1',
      orderId: 'order-1',
      type: 'order',
      status: 'settled',
      isEstimated: false,
      keyword: 'TT-1',
      from: '2026-08-01T00:00:00Z',
      to: '2026-08-21T00:00:00Z',
      currency: 'USD',
    }

    await financeApi.transactions(transactionParams)
    await financeApi.transaction('transaction-1')
    await financeApi.reconciliation({ shopId: 'shop-1', currency: 'USD' })
    await financeApi.exportCsv('transactions', { shopId: 'shop-1', currency: 'USD' })
    await financeApi.sync({
      shopId: 'shop-1',
      mode: 'backfill',
      from: '2026-08-01T00:00:00Z',
      to: '2026-08-21T00:00:00Z',
    })

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/finance/transactions',
      params: transactionParams,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'get',
      url: '/finance/transactions/transaction-1',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(3, {
      method: 'get',
      url: '/finance/reconciliation',
      params: { shopId: 'shop-1', currency: 'USD' },
    })
    expect(mocks.downloadFile).toHaveBeenCalledWith('/finance/export', {
      method: 'get',
      params: { resource: 'transactions', shopId: 'shop-1', currency: 'USD' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/finance/sync',
      data: {
        shopId: 'shop-1',
        mode: 'backfill',
        from: '2026-08-01T00:00:00Z',
        to: '2026-08-21T00:00:00Z',
      },
    })
  })

  it('uses local Finance fixtures only when explicitly enabled', async () => {
    vi.stubEnv('VITE_FINANCE_USE_MOCK', 'true')
    const { financeApi, isFinanceMock } = await loadFinanceApi()

    const result = await financeApi.overview({ currency: 'USD' })

    expect(isFinanceMock).toBe(true)
    expect(result.items[0]?.currency).toBe('USD')
    expect(mocks.request).not.toHaveBeenCalled()
  })
})
