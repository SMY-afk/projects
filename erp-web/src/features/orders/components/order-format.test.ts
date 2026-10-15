import { describe, expect, it } from 'vitest'
import {
  AFFILIATE_EVIDENCE_LABEL,
  AFFILIATE_LINKED_LABEL,
  formatAttributionDimension,
  formatFulfillmentStatus,
  getAffiliateContentFormLabels,
  getAffiliateOrderDisplay,
  getAffiliateVideoIds,
  getOrderCreatorDisplay,
} from './order-format'

describe('formatFulfillmentStatus', () => {
  it.each([
    ['unfulfilled', '未履约'],
    ['AWAITING_COLLECTION', '待揽收'],
    ['in-transit', '运输中'],
    ['out for delivery', '派送中'],
    ['delivered', '已送达'],
    ['unknown', '未知'],
    ['platform_new_status', '未知'],
    [null, '未知'],
  ])('formats %s as %s', (status, expected) => {
    expect(formatFulfillmentStatus(status)).toBe(expected)
  })
})

describe('formatAttributionDimension', () => {
  it('uses an explicit source-missing label instead of natural traffic', () => {
    expect(formatAttributionDimension('unknown')).toBe('未识别：订单详情未返回来源字段')
    expect(formatAttributionDimension('organic')).toBe('organic')
  })
})

describe('getAffiliateOrderDisplay', () => {
  it('shows exact affiliate evidence without inventing a video or live entry point', () => {
    const display = getAffiliateOrderDisplay([
      {
        mainOrderId: 'main-1',
        creatorId: 'creator-1',
        creatorNickname: 'Creator One',
        productId: 'product-1',
        skuId: 'sku-1',
        orderCreatedAt: '2026-08-18T00:00:00Z',
        commissionCurrency: 'USD',
        estimatedStandardCommission: '14.6700',
      },
    ])

    expect(display).toEqual({
      chainLabel: AFFILIATE_LINKED_LABEL,
      creatorLabel: 'Creator One',
      commissionLabel: '预计佣金 US$14.67',
      itemCount: 1,
    })
    expect(AFFILIATE_EVIDENCE_LABEL).toBe('联盟证据已关联')
  })

  it('returns null when no affiliate item is linked', () => {
    expect(getAffiliateOrderDisplay([])).toBeNull()
  })
})

describe('getAffiliateContentFormLabels', () => {
  it('uses Seller Center labels and removes duplicate SKU values', () => {
    expect(
      getAffiliateContentFormLabels([
        {
          mainOrderId: 'main-1',
          productId: 'product-1',
          skuId: 'sku-1',
          orderCreatedAt: '2026-08-18T00:00:00Z',
          promotionType: 2,
          promotionId: '9371233970479993847',
          contentForm: 'video',
          contentFormLabel: '视频',
        },
        {
          mainOrderId: 'main-1',
          productId: 'product-1',
          skuId: 'sku-2',
          orderCreatedAt: '2026-08-18T00:00:00Z',
          promotionType: 2,
          promotionId: '9371233970479993847',
          contentForm: 'video',
          contentFormLabel: '视频',
        },
        {
          mainOrderId: 'main-1',
          productId: 'product-2',
          skuId: 'sku-3',
          orderCreatedAt: '2026-08-18T00:00:00Z',
          promotionType: 3,
          contentForm: 'live',
        },
      ]),
    ).toEqual(['视频', '直播'])
  })

  it('returns unique promotion IDs only for video content', () => {
    const items = [
      {
        mainOrderId: 'main-1',
        productId: 'product-1',
        skuId: 'sku-1',
        orderCreatedAt: '2026-08-18T00:00:00Z',
        promotionType: 2,
        promotionId: '9371233970479993847',
        contentForm: 'video',
      },
      {
        mainOrderId: 'main-1',
        productId: 'product-2',
        skuId: 'sku-2',
        orderCreatedAt: '2026-08-18T00:00:00Z',
        promotionType: 2,
        promotionId: '9371233970479993847',
        contentForm: 'video',
      },
      {
        mainOrderId: 'main-1',
        productId: 'product-3',
        skuId: 'sku-3',
        orderCreatedAt: '2026-08-18T00:00:00Z',
        promotionType: 3,
        promotionId: 'live-1',
        contentForm: 'live',
      },
    ]

    expect(getAffiliateVideoIds(items)).toEqual(['9371233970479993847'])
  })

  it('returns no label when the order has no Affiliate content-form data', () => {
    expect(getAffiliateContentFormLabels([])).toEqual([])
  })
})

describe('getOrderCreatorDisplay', () => {
  it('returns the verified merchant account alias and Creator ID', () => {
    expect(
      getOrderCreatorDisplay({
        trafficSource: 'unknown',
        operatorSubject: 'self_operated',
        entryPoint: 'unknown',
        specialOrderType: 'unknown',
        chainCode: 'unknown',
        classificationStatus: 'derived',
        creatorExternalId: '9443421243333405023',
        creatorHandle: 'pinky__shop4',
        creatorAlias: 'pinky66_shop',
      }),
    ).toEqual({
      creatorId: '9443421243333405023',
      alias: 'pinky66_shop',
    })
  })

  it('returns null when no export creator evidence is available', () => {
    expect(
      getOrderCreatorDisplay({
        trafficSource: 'unknown',
        operatorSubject: 'unknown',
        entryPoint: 'unknown',
        specialOrderType: 'unknown',
        chainCode: 'unknown',
        classificationStatus: 'unknown',
      }),
    ).toBeNull()
  })

  it('does not treat an Affiliate creator nickname as a merchant account alias', () => {
    expect(
      getOrderCreatorDisplay({
        trafficSource: 'unknown',
        operatorSubject: 'creator',
        entryPoint: 'unknown',
        specialOrderType: 'unknown',
        chainCode: 'unknown',
        classificationStatus: 'derived',
        creatorExternalId: '9677336294324206133',
      }),
    ).toBeNull()
  })
})
