import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LogisticsPackageDraftUpdateRequest, LogisticsReviewRequest } from '../types/logistics.types'

const mocks = vi.hoisted(() => ({ request: vi.fn(), uploadFile: vi.fn() }))

vi.mock('@/services/http-client', () => mocks)

async function loadApi() {
  vi.resetModules()
  return import('./logistics.api')
}

describe('logistics page data contract', () => {
  afterEach(() => {
    mocks.request.mockReset()
    mocks.uploadFile.mockReset()
  })

  it('keeps task center and detail paths stable', async () => {
    mocks.request.mockResolvedValue({ items: [], total: 0, page: 1, pageSize: 20 })
    const { logisticsApi } = await loadApi()
    const params = {
      page: 1,
      pageSize: 20,
      shopId: 'shop-1',
      status: 'pending_review' as const,
      sourceType: 'sales_order' as const,
      priority: 'urgent' as const,
      createdFrom: '2026-08-01T00:00:00Z',
      createdTo: '2026-09-01T00:00:00Z',
    }

    await logisticsApi.listTasks(params)
    await logisticsApi.getTask('task-1')
    await logisticsApi.listShops()

    expect(mocks.request).toHaveBeenNthCalledWith(1, { method: 'get', url: '/logistics/tasks', params })
    expect(mocks.request).toHaveBeenNthCalledWith(2, { method: 'get', url: '/logistics/tasks/task-1' })
    expect(mocks.request).toHaveBeenNthCalledWith(3, { method: 'get', url: '/logistics/shops' })
    expect(JSON.stringify(params)).not.toMatch(/warehouse/i)
  })

  it('sends review and package editor payloads without recipient PII', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()
    const review: LogisticsReviewRequest = {
      items: [{ taskItemId: 'item-1', actualQuantity: 1, differenceReason: 'shortage' }],
      note: '少一件',
    }
    const packageDraft: LogisticsPackageDraftUpdateRequest = {
      versionId: 1,
      items: [{ taskItemId: 'item-1', quantity: 1 }],
      weightGrams: 500,
      lengthMm: 200,
      widthMm: 150,
      heightMm: 100,
      note: null,
    }

    await logisticsApi.reviewTask('task-1', review)
    await logisticsApi.createPackageDraft('task-1', { note: null })
    await logisticsApi.updatePackageDraft('package-1', packageDraft)
    await logisticsApi.sealPackage('package-1', 2)
    await logisticsApi.unsealPackage('package-1', 3)

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'post',
      url: '/logistics/tasks/task-1/reviews',
      data: review,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/logistics/tasks/task-1/packages',
      data: { note: null },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(3, {
      method: 'patch',
      url: '/logistics/packages/package-1',
      data: packageDraft,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/logistics/packages/package-1/seal',
      data: { versionId: 2 },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(5, {
      method: 'post',
      url: '/logistics/packages/package-1/unseal',
      data: { versionId: 3 },
    })
    expect(JSON.stringify(mocks.request.mock.calls)).not.toMatch(/recipient|address|phone/i)
  })

  it('loads masked order context and reveals recipient through the protected order endpoint', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()

    await logisticsApi.getOrderContext('task-1')
    await logisticsApi.getRecipient('order-1')

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/logistics/tasks/task-1/order-context',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'get',
      url: '/orders/order-1/recipient',
    })
  })

  it('confirms manual picking and resolves order or SKU scans without location data', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()

    await logisticsApi.confirmPicking('task-1')
    await logisticsApi.resolveScan('SELLER-SKU-1', 'task-1')

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'post',
      url: '/logistics/tasks/task-1/picking-completion',
      data: { note: null },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/logistics/scans/resolve',
      data: { code: 'SELLER-SKU-1', taskId: 'task-1' },
    })
    expect(JSON.stringify(mocks.request.mock.calls)).not.toMatch(/location|wave|inventory|stock/i)
  })

  it('loads package data separately from task detail', async () => {
    mocks.request.mockResolvedValue([])
    const { logisticsApi } = await loadApi()

    await logisticsApi.listPackages('task-1')

    expect(mocks.request).toHaveBeenCalledWith({
      method: 'get',
      url: '/logistics/tasks/task-1/packages',
    })
  })

  it('supports carrier quotes, manual waybills, cancellation and labels', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()
    const waybill = {
      carrierId: 'carrier-1',
      serviceId: 'service-1',
      accountId: null,
      trackingNumber: 'TRACK-123456',
      externalWaybillId: null,
    }

    await logisticsApi.listCarriers()
    await logisticsApi.quoteShipping('package-1')
    await logisticsApi.listWaybills('package-1')
    await logisticsApi.createWaybill('package-1', waybill)
    await logisticsApi.cancelWaybill('waybill-1', 2, '重新选择服务')
    await logisticsApi.getWaybillLabel('waybill-1')
    const label = new File(['label'], 'label.pdf', { type: 'application/pdf' })
    await logisticsApi.uploadWaybillLabel('waybill-1', label)
    const invoice = new File(['amount'], 'invoice.csv', { type: 'text/csv' })
    await logisticsApi.getCarrierInvoiceDocument('invoice-1')
    await logisticsApi.uploadCarrierInvoiceDocument('invoice-1', invoice)
    const proof = new File(['jpeg'], 'proof.jpg', { type: 'image/jpeg' })
    await logisticsApi.getReturnProofDocument('return-1')
    await logisticsApi.uploadReturnProofDocument('return-1', proof)
    const dispatch = {
      packageVersionId: 3,
      waybillId: 'waybill-1',
      waybillVersionId: 2,
      items: [{ taskItemId: 'item-1', quantity: 1 }],
      note: null,
    }
    await logisticsApi.dispatchPackage('package-1', dispatch)

    expect(mocks.request).toHaveBeenNthCalledWith(1, { method: 'get', url: '/logistics/carriers' })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/logistics/packages/package-1/shipping-quotes',
      data: {},
    })
    expect(mocks.request).toHaveBeenNthCalledWith(3, {
      method: 'get',
      url: '/logistics/packages/package-1/waybills',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/logistics/packages/package-1/waybills',
      data: waybill,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(5, {
      method: 'post',
      url: '/logistics/waybills/waybill-1/cancel',
      data: { versionId: 2, reason: '重新选择服务' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(6, {
      method: 'get',
      url: '/logistics/waybills/waybill-1/label',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(7, {
      method: 'get',
      url: '/logistics/carrier-invoices/invoice-1/document',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(8, {
      method: 'get',
      url: '/logistics/return-proofs/return-1/document',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(9, {
      method: 'post',
      url: '/logistics/packages/package-1/dispatch',
      data: dispatch,
    })
    expect(mocks.uploadFile).toHaveBeenCalledWith('/logistics/waybills/waybill-1/label', label)
    expect(mocks.uploadFile).toHaveBeenCalledWith('/logistics/carrier-invoices/invoice-1/document', invoice)
    expect(mocks.uploadFile).toHaveBeenCalledWith('/logistics/return-proofs/return-1/document', proof)
  })

  it('uses the same waybill endpoint for an online carrier without a client tracking number', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()
    const waybill = {
      carrierId: 'carrier-online',
      serviceId: 'service-express',
      accountId: 'account-1',
      trackingNumber: null,
      externalWaybillId: null,
    }

    await logisticsApi.createWaybill('package-1', waybill)

    expect(mocks.request).toHaveBeenCalledWith({
      method: 'post',
      url: '/logistics/packages/package-1/waybills',
      data: waybill,
    })
  })

  it('generates one or more task plans from sales order lines', async () => {
    mocks.request.mockResolvedValue({ items: [] })
    const { logisticsApi } = await loadApi()
    const data = {
      orderId: 'order-1',
      tasks: [
        { items: [{ orderLineId: 'line-1', plannedQuantity: 1 }], priority: 'normal' as const, note: null },
        { items: [{ orderLineId: 'line-2', plannedQuantity: 2 }], priority: 'high' as const, note: '单独发货' },
      ],
    }

    await logisticsApi.generateTasks(data)

    expect(mocks.request).toHaveBeenCalledWith({
      method: 'post',
      url: '/logistics/tasks/generate',
      data,
    })
  })

  it('supports the exception center list and processing actions', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()
    const params = { page: 1, pageSize: 20, status: 'open' as const, assignedToMe: true }

    await logisticsApi.listExceptions(params)
    await logisticsApi.claimException('exception-1', 1)
    await logisticsApi.noteException('exception-1', 2, '已联系物流商')
    await logisticsApi.escalateException('exception-1', 3, 'critical', '疑似丢失')
    await logisticsApi.resolveException('exception-1', 4, '找到包裹并恢复运输')
    await logisticsApi.closeException('exception-1', 5, '复盘完成')
    await logisticsApi.detectExceptions()
    await logisticsApi.syncPlatformLogistics()

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'get',
      url: '/logistics/exceptions',
      params,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/logistics/exceptions/exception-1/claim',
      data: { versionId: 1 },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(3, {
      method: 'post',
      url: '/logistics/exceptions/exception-1/notes',
      data: { versionId: 2, note: '已联系物流商' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(4, {
      method: 'post',
      url: '/logistics/exceptions/exception-1/escalate',
      data: { versionId: 3, severity: 'critical', note: '疑似丢失' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(5, {
      method: 'post',
      url: '/logistics/exceptions/exception-1/resolve',
      data: { versionId: 4, resolution: '找到包裹并恢复运输' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(6, {
      method: 'post',
      url: '/logistics/exceptions/exception-1/close',
      data: { versionId: 5, note: '复盘完成' },
    })
    expect(mocks.request).toHaveBeenNthCalledWith(7, {
      method: 'post',
      url: '/logistics/exceptions/detect',
    })
    expect(mocks.request).toHaveBeenNthCalledWith(8, {
      method: 'post',
      url: '/logistics/exceptions/sync-platform',
    })
  })

  it('manages carrier master data and platform mappings', async () => {
    mocks.request.mockResolvedValue({})
    const { logisticsApi } = await loadApi()
    const carrier = { code: 'UPS', name: 'UPS', adapterKey: 'manual', trackingUrlTemplate: null }
    const service = {
      code: 'GROUND',
      name: 'Ground',
      serviceLevel: 'standard',
      supportedCountries: ['US'],
      platformProviderIds: {},
      trackingStatusMap: {},
    }
    const mapping = {
      storeId: 'store-1',
      platform: 'tiktok',
      region: 'US',
      serviceId: null,
      platformCarrierId: '123456789',
      platformCarrierCode: 'UPS',
      platformCarrierName: 'UPS',
      deliveryOptionId: 'delivery-option-1',
    }

    await logisticsApi.createCarrier(carrier)
    await logisticsApi.createCarrierService('carrier-1', service)
    await logisticsApi.createPlatformCarrierMapping('carrier-1', mapping)
    await logisticsApi.updatePlatformCarrierMapping('mapping-1', { versionId: 1, status: 'inactive' })

    expect(mocks.request).toHaveBeenNthCalledWith(1, {
      method: 'post',
      url: '/logistics/carriers',
      data: carrier,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(2, {
      method: 'post',
      url: '/logistics/carriers/carrier-1/services',
      data: service,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(3, {
      method: 'post',
      url: '/logistics/carriers/carrier-1/platform-mappings',
      data: mapping,
    })
    expect(mocks.request).toHaveBeenNthCalledWith(4, {
      method: 'patch',
      url: '/logistics/platform-carrier-mappings/mapping-1',
      data: { versionId: 1, status: 'inactive' },
    })
  })

  it('normalizes carrier collections during a rolling backend restart', async () => {
    mocks.request.mockResolvedValue([{ id: 'carrier-1', code: 'UPS', name: 'UPS' }])
    const { logisticsApi } = await loadApi()

    const carriers = await logisticsApi.listCarriers()

    expect(carriers[0]).toMatchObject({ services: [], accounts: [], platformMappings: [] })
  })
})
