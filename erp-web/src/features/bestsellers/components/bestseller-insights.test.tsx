import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { BestsellerEntry } from '../types/bestseller.types'
import { BestsellerInsights } from './bestseller-insights'

const entry = (overrides: Partial<BestsellerEntry> = {}): BestsellerEntry => ({
  entityType: 'product',
  externalId: 'item-1',
  rank: 1,
  displayName: 'Top item',
  gmv: { raw: '$10K-$20K', currencyContext: 'USD', computable: false },
  extensions: {},
  ...overrides,
})

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  })
})

describe('BestsellerInsights', () => {
  it('shows sourcing signals without calculating GMV', () => {
    render(
      <BestsellerInsights
        entity="products"
        entries={[
          entry({ extensions: { shop_name: 'Shop A', rating: '4.8' } }),
          entry({ externalId: 'item-2', extensions: { shop_name: 'Shop B' } }),
        ]}
      />,
    )

    expect(screen.getByText('选品概览')).toBeInTheDocument()
    expect(screen.getByText('上榜商品')).toBeInTheDocument()
    expect(screen.getByText('覆盖店铺')).toBeInTheDocument()
    expect(screen.getByText('榜首 GMV 区间')).toBeInTheDocument()
    expect(screen.getByText('$10K-$20K')).toBeInTheDocument()
  })

  it('derives creator and video decision signals from verified fields', () => {
    const { rerender } = render(
      <BestsellerInsights
        entity="creators"
        entries={[
          entry({ entityType: 'creator', extensions: { followers_count: 1000, likes_count: 5000 } }),
          entry({ entityType: 'creator', externalId: 'creator-2', extensions: { followers_count: 3000 } }),
        ]}
      />,
    )
    expect(screen.getByText('达人筛选概览')).toBeInTheDocument()
    expect(screen.getByText('粉丝中位数')).toBeInTheDocument()

    rerender(
      <BestsellerInsights
        entity="videos"
        entries={[
          entry({
            entityType: 'video',
            extensions: { views: 1000, likes: 100, comments: 20, shares: 10, product_infos: [{ product_id: 'p1' }] },
          }),
        ]}
      />,
    )
    expect(screen.getByText('视频内容表现')).toBeInTheDocument()
    expect(screen.getByText('互动率中位数')).toBeInTheDocument()
    expect(screen.getByText('13%')).toBeInTheDocument()
  })
})
