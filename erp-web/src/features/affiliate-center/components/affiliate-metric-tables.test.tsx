import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { AffiliateCreatorMetric, AffiliateVideoMetric } from '../types/affiliate-center.types'
import { CreatorMetricTable } from './creator-metric-table'
import { VideoMetricTable } from './video-metric-table'
import { AffiliateRangeSummary } from './affiliate-range-summary'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})

describe('Affiliate Center metric tables', () => {
  it('shows creator totals for the complete selected date range', () => {
    render(
      <AffiliateRangeSummary
        from="2026-08-01"
        loading={false}
        resource="creators"
        summary={{
          creatorCount: 12,
          affiliateGmvMinor: 12345,
          estimatedCommissionMinor: 1234,
          itemsSold: 30,
          affiliateOrderCount: 20,
          productImpressions: 4567,
        }}
        to="2026-08-05"
        currency="USD"
      />,
    )

    expect(screen.getByText('所选 5 天汇总')).toBeInTheDocument()
    expect(screen.getByText('达人总数')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('$123.45')).toBeInTheDocument()
    expect(screen.getByText('4,567')).toBeInTheDocument()
  })

  it('shows video totals instead of only the current page values', () => {
    render(
      <AffiliateRangeSummary
        from="2026-08-01"
        loading={false}
        resource="videos"
        summary={{
          videoCount: 80,
          gmvMinor: 45678,
          orderCount: 50,
          itemsSold: 60,
          views: 123456,
          productImpressions: 7890,
        }}
        to="2026-08-25"
        currency="USD"
      />,
    )

    expect(screen.getByText('所选 25 天汇总')).toBeInTheDocument()
    expect(screen.getByText('视频总数')).toBeInTheDocument()
    expect(screen.getByText('80')).toBeInTheDocument()
    expect(screen.getByText('$456.78')).toBeInTheDocument()
    expect(screen.getByText('123,456')).toBeInTheDocument()
  })

  it('shows the requested creator identity and performance fields', () => {
    const creator = {
      id: 'creator-1',
      username: '@creator',
      creatorOpenId: 'open-1',
      avatarUrl: 'https://example.test/avatar.jpg',
      affiliateGmvMinor: 12345,
      estimatedCommissionMinor: 1234,
      itemsSold: 8,
      affiliateOrderCount: 6,
      averageAffiliateCustomers: '4',
      clickThroughRate: '0.0189',
    } as AffiliateCreatorMetric

    render(
      <CreatorMetricTable
        currency="USD"
        items={[creator]}
        loading={false}
        page={1}
        shopName="Akeleo Fun Toys"
        total={1}
        onPageChange={() => {}}
      />,
    )

    for (const heading of [
      '店铺名',
      '达人',
      '达人身份',
      '联盟 GMV',
      '预计佣金',
      '成交件数',
      '订单量',
      '客户数',
      '点击率',
    ]) {
      expect(screen.getByRole('columnheader', { name: heading })).toBeInTheDocument()
    }
    expect(screen.getByText('Akeleo Fun Toys')).toBeInTheDocument()
    expect(screen.getByText('@creator')).toBeInTheDocument()
    expect(screen.getByText('Open ID · open-1')).toBeInTheDocument()
    expect(screen.getByText('$123.45')).toBeInTheDocument()
    expect(screen.getByText('1.89%')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '@creator' })).toHaveAttribute('referrerpolicy', 'no-referrer')
  })

  it('shows the requested video content and performance fields', () => {
    const video: AffiliateVideoMetric = {
      id: 'video-1',
      videoId: 'video-1',
      coverImageUrl: 'https://example.test/cover.jpg',
      title: 'Video title',
      creatorUsername: 'jennaclary4',
      creatorNickname: 'Jenna Clary',
      videoPostTime: '2026-08-25T00:00:00Z',
      promotedProducts: [
        { productId: 'product-1', title: 'Remote car', coverImageUrl: 'https://example.test/product.jpg' },
      ],
      views: 300,
      gmvMinor: 4567,
      orderCount: 2,
      productClickThroughRate: '0.05',
    }

    render(
      <VideoMetricTable currency="USD" items={[video]} loading={false} page={1} total={1} onPageChange={() => {}} />,
    )

    for (const heading of ['视频', '达人', '发布时间', '商品', '观看量', 'GMV', '订单', '点击率']) {
      expect(screen.getByRole('columnheader', { name: heading })).toBeInTheDocument()
    }
    expect(screen.getByAltText('视频封面')).toBeInTheDocument()
    expect(screen.getByText('Video title')).toBeInTheDocument()
    expect(screen.getByText('jennaclary4')).toBeInTheDocument()
    expect(screen.queryByText('Jenna Clary')).not.toBeInTheDocument()
    expect(screen.getByText('Remote car')).toBeInTheDocument()
    expect(screen.getByAltText('Remote car')).toBeInTheDocument()
    expect(screen.getByText('$45.67')).toBeInTheDocument()
    expect(screen.getByText('5.00%')).toBeInTheDocument()
  })

  it('constrains long video and product text without squeezing metric columns', () => {
    const longTitle = 'A very long video title '.repeat(12).trim()
    const longProductTitle = 'A very long product title '.repeat(12).trim()
    const video: AffiliateVideoMetric = {
      id: 'video-long',
      videoId: 'video-long',
      title: longTitle,
      creatorNickname: 'Creator with a long display name',
      videoPostTime: '2026-08-25T00:00:00Z',
      promotedProducts: [{ productId: 'product-long', title: longProductTitle, coverImageUrl: null }],
      views: 300,
      gmvMinor: 4567,
      orderCount: 2,
      productClickThroughRate: '0.05',
    }

    render(
      <VideoMetricTable currency="USD" items={[video]} loading={false} page={1} total={1} onPageChange={() => {}} />,
    )

    expect(screen.getByRole('table')).toHaveStyle({ tableLayout: 'fixed' })
    expect(screen.getByText(longTitle)).toHaveClass('affiliate-video-title')
    expect(screen.getByText(longProductTitle)).toHaveClass('affiliate-video-product-title')
    expect(screen.getByText('$45.67').closest('td')).toHaveClass('affiliate-video-metric-cell')
  })

  it('renders product ids as image cards instead of plain numeric text', () => {
    const video: AffiliateVideoMetric = {
      id: 'video-product-id',
      videoId: 'video-product-id',
      title: 'Video title',
      promotedProductIds: ['9886166395461732977'],
    }

    render(
      <VideoMetricTable currency="USD" items={[video]} loading={false} page={1} total={1} onPageChange={() => {}} />,
    )

    expect(screen.getByLabelText('商品图片占位')).toBeInTheDocument()
    expect(screen.queryByText('9886166395461732977')).not.toBeInTheDocument()
  })

  it('uses the related product image when a source video has no cover', () => {
    const video: AffiliateVideoMetric = {
      id: 'video-cover-fallback',
      videoId: 'video-cover-fallback',
      title: 'Video title',
      coverImageUrl: null,
      promotedProducts: [
        { productId: 'product-1', title: 'Remote car', coverImageUrl: 'https://example.test/product.jpg' },
      ],
    }

    render(
      <VideoMetricTable currency="USD" items={[video]} loading={false} page={1} total={1} onPageChange={() => {}} />,
    )

    expect(screen.getByAltText('关联商品图片')).toHaveAttribute('src', 'https://example.test/product.jpg')
    expect(screen.queryByText('无封面')).not.toBeInTheDocument()
  })

  it('falls back to the related product image when the video cover fails', () => {
    const video: AffiliateVideoMetric = {
      id: 'video-expired-cover',
      videoId: 'video-expired-cover',
      title: 'Video title',
      coverImageUrl: 'https://expired.test/cover.jpg',
      promotedProducts: [
        { productId: 'product-1', title: 'Remote car', coverImageUrl: 'https://example.test/product.jpg' },
      ],
    }

    render(
      <VideoMetricTable currency="USD" items={[video]} loading={false} page={1} total={1} onPageChange={() => {}} />,
    )

    fireEvent.error(screen.getByAltText('视频封面'))

    expect(screen.getByAltText('关联商品图片')).toHaveAttribute('src', 'https://example.test/product.jpg')
  })
})
