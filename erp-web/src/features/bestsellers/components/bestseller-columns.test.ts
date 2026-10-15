import { describe, expect, it } from 'vitest'
import { creatorRankingColumns } from './creator-ranking-columns'
import { liveRankingColumns } from './live-ranking-columns'
import { productRankingColumns } from './product-ranking-columns'
import { videoRankingColumns } from './video-ranking-columns'

describe('Bestseller ranking columns', () => {
  it.each([
    ['products', productRankingColumns],
    ['creators', creatorRankingColumns],
    ['videos', videoRankingColumns],
    ['lives', liveRankingColumns],
  ])('fixes only rank and subject for %s', (_, columns) => {
    expect(columns[0]?.fixed).toBe('left')
    expect(columns[1]?.fixed).toBe('left')
    expect(columns.slice(2).every((column) => column.fixed === undefined)).toBe(true)
  })

  it('exposes verified sourcing and content-analysis fields', () => {
    expect(productRankingColumns.map((column) => column.title)).toEqual(
      expect.arrayContaining(['店铺', '评分', 'GMV 区间']),
    )
    expect(videoRankingColumns.map((column) => column.title)).toEqual(expect.arrayContaining(['时长', '互动率']))
    expect(liveRankingColumns.map((column) => column.title)).toEqual(
      expect.arrayContaining(['主播', '开播时间', '直播时长']),
    )
  })
})
