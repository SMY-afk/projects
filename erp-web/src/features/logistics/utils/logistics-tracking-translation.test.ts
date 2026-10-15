import { describe, expect, it } from 'vitest'
import { translateTrackingDescription } from './logistics-tracking-translation'

describe('tracking description translation for Excel', () => {
  it.each([
    ['Order placed.', '已下单。'],
    ['Package details received by the carrier.', '承运商已收到包裹详细信息。'],
    ['Order packed and ready for pickup.', '订单已打包，正在等待承运商揽收。'],
    ["Order packed and ready for dropoff at carrier's facility.", '订单已打包，正在等待在承运商的仓储场所卸货。'],
    ['Package is being prepared at warehouse.', '包裹正在仓库备货。'],
    ['Package is ready and will be handed over to the carrier soon.', '包裹已准备好，即将交给承运商。'],
    ['In transit', '运输中。'],
    ['In transit to the next facility.', '正在运往下一个仓储场所。'],
    ['Out for delivery.', '正在派送。'],
    ['Package has been delivered!', '包裹已送达。'],
    ['Delivered, Front Door/Porch', '已送达，前门/门廊。'],
    ['Delivered, Front Desk/Reception/Mail Room', '已送达，前台/接待处/收发室。'],
    ['Package picked up and currently at CHINO.', '包裹已被揽收，目前位于CHINO。'],
    ["Arrived at the CHINO carrier's facility.", '已到达承运商的CHINO仓储场所。'],
    ["Departed the GOODYEAR carrier's facility.", '已离开承运商的GOODYEAR仓储场所。'],
    ["Arrived at the CITY OF INDUSTRY CA DISTRIBUTION CENTER carrier's facility.", '已到达承运商的CITY OF INDUSTRY CA DISTRIBUTION CENTER仓储场所。'],
    ["Arrived at the O'Fallon carrier's facility.", "已到达承运商的O'Fallon仓储场所。"],
    ["Departed the Melrose Park shipping partner's facility.", '已离开物流合作伙伴的Melrose Park仓储场所。'],
    ['Arrived at the MENIFEE destination facility.', '已到达MENIFEE目的地仓储场所。'],
    ['  OUT FOR DELIVERY!  ', '正在派送。'],
  ])('translates %s while retaining place names', (source, expected) => {
    expect(translateTrackingDescription(source)).toBe(expected)
  })

  it.each([undefined, null, ''])('keeps missing descriptions empty: %s', (source) => {
    expect(translateTrackingDescription(source)).toBe('')
  })

  it.each(['已到达承运商的CHINO仓储场所。', 'Shipment delayed near CHINO; awaiting inspection.',
    'Delivered, Unrecognized delivery location', '=UNTRUSTED()', '__proto__', 'constructor'])('preserves unsupported descriptions without guessing: %s', (source) => {
    expect(translateTrackingDescription(source)).toBe(source)
  })
})
