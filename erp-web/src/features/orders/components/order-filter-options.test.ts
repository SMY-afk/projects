import { describe, expect, it } from 'vitest'
import {
  affiliateContentFormOptions,
  getOrderTypeFilters,
  getOrderTypePath,
  orderTypeOptions,
} from './order-filter-options'

describe('affiliate content form filter options', () => {
  it('matches the five Seller Center content forms', () => {
    expect(affiliateContentFormOptions).toEqual([
      { value: 'video', label: '视频' },
      { value: 'live', label: '直播' },
      { value: 'product_showcase', label: '商品橱窗' },
      { value: 'affiliate_product_page', label: '联盟商品页' },
      { value: 'external_traffic_plan', label: '外部流量计划' },
    ])
  })
})

describe('sample order filter option', () => {
  it('makes the zero-amount rule explicit', () => {
    const sampleOption = orderTypeOptions.find((option) => option.value === 'sample')

    expect(sampleOption).toEqual({ value: 'sample', label: '样品订单（金额为0）' })
  })
})

describe('transaction-chain filter path', () => {
  it('uses filter options backed by the currently available evidence', () => {
    expect(orderTypeOptions.slice(0, 4).map(({ value, label }) => ({ value, label }))).toEqual([
      { value: 'all', label: '全部成交链路' },
      { value: 'creator', label: '联盟达人订单' },
      { value: 'self_operated', label: '自家订单' },
      { value: 'unknown', label: '来源待识别' },
    ])
  })

  it('maps affiliate content and reset selections to API filters', () => {
    expect(getOrderTypeFilters(['creator', 'video'])).toEqual({
      operatorSubject: 'creator',
      contentForm: 'video',
    })
    expect(getOrderTypeFilters(['self_operated'])).toEqual({ operatorSubject: 'self_operated' })
    expect(getOrderTypeFilters(['unknown'])).toEqual({ operatorSubject: 'unknown' })
    expect(getOrderTypeFilters(['all'])).toEqual({})
    expect(getOrderTypeFilters(undefined)).toEqual({})
  })

  it('restores affiliate content and sample selections from list params', () => {
    expect(
      getOrderTypePath({
        page: 1,
        pageSize: 20,
        operatorSubject: 'creator',
        contentForm: 'video',
      }),
    ).toEqual(['creator', 'video'])
    expect(getOrderTypePath({ page: 1, pageSize: 20, specialOrderType: 'sample' })).toEqual(['sample'])
    expect(getOrderTypePath({ page: 1, pageSize: 20 })).toBeUndefined()
  })
})
