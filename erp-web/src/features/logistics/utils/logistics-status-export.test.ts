import { afterEach, describe, expect, it, vi } from 'vitest'
import { unzipSync, strFromU8 } from 'fflate'
import { buildLogisticsStatusExcel } from './logistics-status-export'
import type { LogisticsStatusOrder, LogisticsStatusLive } from '../types/logistics-status.types'
import { liveFixture } from './logistics-status-test-fixture'

const order: LogisticsStatusOrder = {
  id: 'order-1',
  shopId: 'shop-1',
  shopName: '=UNTRUSTED()',
  orderNumber: '982740775181726442',
  orderCreatedAt: '2026-10-07T08:52:41Z',
  platformStatus: 'COMPLETED',
  platformUpdatedAt: '2026-10-12T01:00:00Z',
  erpSyncedAt: '2026-10-12T02:00:00Z',
  packages: [
    {
      packageId: '9678255960213414736',
      packageStatus: 'COMPLETED',
      carrierName: null,
      trackingNumberMasked: '****5920',
      trackingStatus: 'delivered',
      trackingCheckedAt: '2026-10-10T01:00:00Z',
    },
  ],
}
const live: LogisticsStatusLive = {
  ...liveFixture,
  shippedAt: '2026-10-07T08:52:41.503Z',
  orderId: order.id,
  trackingStatus: 'in_transit',
  checkedAt: '2026-10-12T03:00:00Z',
  packages: order.packages,
  events: [
    { status: 'ready_for_collection', occurredAt: '2026-10-07T09:52:41Z', description: 'Order packed and ready for pickup.', actionCode: '20101' },
    { status: 'in_transit', occurredAt: '2026-10-12T02:30:00Z', description: 'In transit', actionCode: '32501' },
  ],
}

async function readWorkbook(liveByOrder: Record<string, LogisticsStatusLive>, failures: Record<string, string> = {}) {
  const result = await buildLogisticsStatusExcel([order], liveByOrder, 'Test/Shop', failures, { [order.shopId]: 'America/Los_Angeles' })
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as ArrayBuffer)
    reader.onerror = reject
    reader.readAsArrayBuffer(result.blob)
  })
  const entries = unzipSync(new Uint8Array(buffer))
  const xml = Object.fromEntries(Object.entries(entries).map(([name, value]) => [name, strFromU8(value)]))
  return { result, xml, content: Object.values(xml).join('\n') }
}

describe('logistics Excel export', () => {
  afterEach(() => vi.useRealTimers())
  it('rejects an export that only has stale cached rows', async () => {
    await expect(buildLogisticsStatusExcel([order], {}, 'Shop')).rejects.toThrow('fresh official result')
  })

  it('retains ERP creation time for failed queries and leaves official nodes empty', async () => {
    const { xml, content } = await readWorkbook({}, { [order.id]: '官方实时查询失败' })
    expect(content).toContain('官方实时查询失败')
    expect(content).not.toContain(order.packages[0].packageId)
    const document = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    expect(document.querySelector('c[r="E5"] v')).not.toBeNull()
    for (const column of ['F', 'G', 'H', 'L']) expect(document.querySelector(`c[r="${column}5"] v`)).toBeNull()
    expect(document.querySelector('c[r="O5"] v')).toBeNull()
    expect(Number(document.querySelector('c[r="P5"] v')?.textContent)).toBeCloseTo(
      Math.floor(Date.parse(order.erpSyncedAt) / 1000) / 86400 + 25569 + 8 / 24, 9,
    )
  })

  it('keeps long identifiers and formula-like input as text in a real XLSX file', async () => {
    const { result, xml, content } = await readWorkbook({ [order.id]: live })
    expect(result.fileName).toMatch(/^物流状态_Test_Shop_\d+\.xlsx$/)
    expect(content).toContain(order.orderNumber)
    expect(content).toContain(order.packages[0].packageId)
    expect(content).toContain('=UNTRUSTED()')
    expect(xml['xl/worksheets/sheet1.xml']).toMatch(/<c[^>]*r="B5"[^>]*t="s"/)
    expect(content).not.toContain('<f>=UNTRUSTED()')
    expect(content).not.toContain('上次官方同步')
    expect(content).toContain('ERP全部订单的下单时间')
    const document = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    const createdSerial = Number(document.querySelector('c[r="E5"] v')?.textContent)
    const createdDisplay = new Date(Math.round((createdSerial - 25569) * 86400_000)).toISOString()
    expect(createdDisplay).toBe('2026-10-07T01:52:41.000Z')
    expect((Number(document.querySelector('c[r="F5"] v')?.textContent) - createdSerial) * 24).toBeCloseTo(1, 6)
    expect(document.querySelector('c[r="I5"] f')?.textContent).toContain('(F5-E5)*24')
    expect(document.querySelector('c[r="J5"] f')?.textContent).toContain('(G5-E5)*24')
  })

  it('exports fresh official results and the first-place evidence rather than cache', async () => {
    const fresh = { ...live, packages: [{ ...order.packages[0], carrierName: 'USPS' },
      { ...order.packages[0], packageId: 'another-package', carrierName: 'FedEx' }] }
    const { content, xml } = await readWorkbook({ [order.id]: fresh })
    expect(content).toContain('运输中')
    expect(content).not.toContain('<t>In transit</t>')
    expect(content).toContain('已到达承运商的CITY OF INDUSTRY CA DISTRIBUTION CENTER仓储场所。')
    expect(content).toContain('CITY OF INDUSTRY CA DISTRIBUTION CENTER')
    expect(xml['xl/workbook.xml']).toContain('官方实时轨迹')
    expect(content).toContain('USPS')
    expect(content).toContain('FedEx')
    expect(content).not.toContain('承运商未知')
  })

  it('places the newest official description directly after first-place evidence', async () => {
    const latest = { status: 'delivered', occurredAt: '2026-10-13T01:00:00Z', description: 'Delivered, Front Door/Porch', actionCode: '40000' }
    const { xml } = await readWorkbook({ [order.id]: { ...live, events: [live.events[0], latest, live.events[1]] } })
    const sheet = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    const strings = new DOMParser().parseFromString(xml['xl/sharedStrings.xml'], 'application/xml')
    const readText = (cell: string) => strings.querySelectorAll('si')[Number(sheet.querySelector(`c[r="${cell}"] v`)?.textContent)]?.textContent
    expect(readText('K4')).toBe('首次地点轨迹依据')
    expect(readText('L4')).toBe('最新轨迹')
    expect(readText('M4')).toBe('发货轨迹依据')
    expect(readText('L5')).toBe('已送达，前门/门廊。')
    expect(readText('K5')).toBe('已到达承运商的CITY OF INDUSTRY CA DISTRIBUTION CENTER仓储场所。')
    expect(readText('M5')).toBe('订单已打包，正在等待承运商揽收。')
    expect(readText('N5')).toBe('已送达，前台/接待处/收发室。')
    const events = new DOMParser().parseFromString(xml['xl/worksheets/sheet2.xml'], 'application/xml')
    const eventText = (cell: string) => strings.querySelectorAll('si')[Number(events.querySelector(`c[r="${cell}"] v`)?.textContent)]?.textContent
    expect(eventText('G2')).toBe('订单已打包，正在等待承运商揽收。')
    expect(eventText('G3')).toBe('已送达，前门/门廊。')
    expect(eventText('G4')).toBe('运输中。')
  })

  it('preserves a successful empty official result', async () => {
    const { content, xml } = await readWorkbook({ [order.id]: { ...live, trackingStatus: null, packages: [], events: [] } })
    const sheet = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    expect(sheet.querySelector('c[r="L5"] v')).toBeNull()
    expect(content).toContain('官方暂无轨迹')
    expect(content).not.toContain('<t>上次官方同步</t>')
    expect(content).not.toContain(order.packages[0].packageId)
  })

  it.each([['SELLER', 'FULFILLMENT_BY_SELLER', '商家物流'], ['TIKTOK', 'FULFILLMENT_BY_SELLER', 'TikTok物流'],
    ['TIKTOK', 'FULFILLMENT_BY_TIKTOK', 'FBT物流']])('exports local milestones and the official shipping method %s/%s', async (shippingType, fulfillmentType, expectedLabel) => {
    const { content, xml } = await readWorkbook({ [order.id]: { ...live, shippingType, fulfillmentType } })
    expect(content).toContain('订单创建时间（当地时间）')
    expect(content).toContain('当地时间的发货时间')
    expect(content).toContain('当地时间的真实发货时间')
    expect(content).toContain('实际送达时间（当地时间）')
    for (const removed of ['真实发货至送达（小时）', '创建至真实发货（小时）', '创建至送达（小时）', '发货至送达（小时）']) {
      expect(content).not.toContain(removed)
    }
    expect(content).toContain(expectedLabel)
    expect(content).toContain('America/Los_Angeles')
    expect(content).toContain('订单数据同步时间（北京时间）')
    const document = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    const intervals = { I: 'F5-E5', J: 'G5-E5' }
    for (const [column, difference] of Object.entries(intervals)) {
      const formula = document.querySelector(`c[r="${column}5"] f`)?.textContent
      expect(formula).toContain(`(${difference})*24`)
      expect(formula).toContain('ISNUMBER')
      expect(formula).not.toMatch(/NOW|TODAY/)
    }
    expect(document.querySelector('c[r="O5"] v')?.textContent).not.toBe(
      document.querySelector('c[r="P5"] v')?.textContent,
    )
  })

  it('keeps delivery and actual shipment intervals fixed when exported on a later day', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-12T00:00:00Z'))
    const first = await readWorkbook({ [order.id]: live })
    vi.setSystemTime(new Date('2026-10-22T00:00:00Z'))
    const later = await readWorkbook({ [order.id]: live })
    const read = (xml: Record<string, string>) =>
      new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    for (const column of ['E', 'F', 'G', 'H', 'I', 'J']) {
      expect(read(later.xml).querySelector(`c[r="${column}5"]`)?.textContent).toBe(
        read(first.xml).querySelector(`c[r="${column}5"]`)?.textContent,
      )
    }
    const serial = (column: string) => Number(read(later.xml).querySelector(`c[r="${column}5"] v`)?.textContent)
    expect((serial('G') - serial('E')) * 86400).toBeCloseTo(166039, 4)
    expect((serial('H') - serial('E')) * 86400).toBeCloseTo(288679, 4)
  })

  it('keeps the background sync timestamp fixed across two fresh export queries', async () => {
    const firstLive = { ...live, erpSyncedAt: order.erpSyncedAt, checkedAt: '2026-10-13T01:00:00Z' }
    const laterLive = { ...firstLive, checkedAt: '2026-10-13T01:10:00Z' }
    const first = await readWorkbook({ [order.id]: firstLive })
    const later = await readWorkbook({ [order.id]: laterLive })
    const serial = (xml: Record<string, string>, cell: string) => Number(
      new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
        .querySelector(`c[r="${cell}"] v`)?.textContent,
    )
    const expected = (value: string) => Math.floor(Date.parse(value) / 1000) / 86400 + 25569 + 8 / 24
    expect(serial(first.xml, 'P5')).toBeCloseTo(expected(order.erpSyncedAt), 9)
    expect(serial(later.xml, 'P5')).toBe(serial(first.xml, 'P5'))
    expect(serial(first.xml, 'O5')).toBeCloseTo(expected(firstLive.checkedAt), 9)
    expect(serial(later.xml, 'O5')).toBeCloseTo(expected(laterLive.checkedAt), 9)
    expect((serial(later.xml, 'O5') - serial(first.xml, 'O5')) * 86400).toBeCloseTo(600, 4)
  })

  it('leaves shipment empty until an official packed event exists', async () => {
    const { xml } = await readWorkbook({ [order.id]: { ...live, events: [] } })
    const document = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    expect(document.querySelector('c[r="F5"] v')).toBeNull()
  })

  it('rejects missing shop timezone rather than exporting Beijing as local time', async () => {
    await expect(buildLogisticsStatusExcel([order], { [order.id]: live }, 'Shop')).rejects.toThrow('timezone')
  })

  it('keeps elapsed hours correct when local clocks cross daylight saving time', async () => {
    const dstLive = { ...live, orderCreatedAt: '2026-11-01T08:30:00Z', firstLocationAt: '2026-11-01T10:30:00Z',
      events: [{ status: 'ready_for_collection', occurredAt: '2026-11-01T09:30:00Z', description: 'Order packed and ready for pickup.', actionCode: '20101' }] }
    const { xml } = await readWorkbook({ [order.id]: dstLive })
    const document = new DOMParser().parseFromString(xml['xl/worksheets/sheet1.xml'], 'application/xml')
    expect(document.querySelector('c[r="I5"] f')?.textContent).toContain('(F5-E5)*24+1')
    expect(document.querySelector('c[r="J5"] f')?.textContent).toContain('(G5-E5)*24+1')
  })
})
