import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { AffiliateFilterBar } from './affiliate-filter-bar'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
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

describe('AffiliateFilterBar', () => {
  it('labels video performance dates separately from publication time', () => {
    render(
      <AffiliateFilterBar
        dateRangeLabel="统计日期（非发布时间）"
        filters={{ shopId: 'shop-1', from: '2026-09-14', to: '2026-09-20', currency: 'USD' }}
        loading={false}
        shops={[]}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('统计日期（非发布时间）')).toBeInTheDocument()
    expect(screen.getAllByLabelText('统计日期（非发布时间）')).toHaveLength(2)
  })

  it('shows the TikTok calendar day separately from a lagging report day', async () => {
    const user = userEvent.setup()
    render(
      <AffiliateFilterBar
        filters={{ shopId: 'shop-1', from: '2026-08-27', to: '2026-09-02', currency: 'USD' }}
        latestAvailableDay="2026-09-02"
        loading={false}
        shops={[]}
        tikTokToday="2026-09-03"
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByText('TK 当地日期：2026-09-03；数据截至：2026-09-02')).toBeInTheDocument()
    await user.click(screen.getAllByLabelText('日期范围')[0])
    expect(await screen.findByText('今天')).toBeInTheDocument()
  })

  it('uses TikTok actual latest selectable date for Today', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <AffiliateFilterBar
        filters={{ shopId: 'shop-1', from: '2026-08-01', to: '2026-08-07', currency: 'USD' }}
        latestAvailableDay="2026-08-29"
        loading={false}
        shops={[
          {
            id: 'shop-1',
            shopName: 'Akeleo Fun Toys',
            timezone: 'America/Los_Angeles',
            currency: 'USD',
          },
        ]}
        onChange={onChange}
      />,
    )

    await user.click(screen.getAllByLabelText('日期范围')[0])
    await user.click(await screen.findByText('今天'))

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-29',
        to: '2026-08-29',
        currency: 'USD',
      }),
    )
  })

  it('anchors quick ranges to the supplied TikTok available date', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <AffiliateFilterBar
        filters={{ shopId: 'shop-1', from: '2026-08-01', to: '2026-08-07', currency: 'USD' }}
        latestAvailableDay="2026-08-24"
        loading={false}
        shops={[
          {
            id: 'shop-1',
            shopName: 'Akeleo Fun Toys',
            timezone: 'America/Los_Angeles',
            currency: 'USD',
          },
        ]}
        onChange={onChange}
      />,
    )

    await user.click(screen.getAllByLabelText('日期范围')[0])
    await user.click(await screen.findByText('最近 7 天'))

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-08-18',
        to: '2026-08-24',
        currency: 'USD',
      }),
    )
  })

  it('rolls the two-month range from the latest TikTok available day', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <AffiliateFilterBar
        enable60DayPreset
        filters={{ shopId: 'shop-1', from: '2026-08-19', to: '2026-08-25', currency: 'USD' }}
        latestAvailableDay="2026-08-31"
        loading={false}
        shops={[
          {
            id: 'shop-1',
            shopName: 'Akeleo Fun Toys',
            timezone: 'America/Los_Angeles',
            currency: 'USD',
          },
        ]}
        onChange={onChange}
      />,
    )

    await user.click(screen.getAllByLabelText('日期范围')[0])
    await user.click(await screen.findByText('近两个月'))

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        shopId: 'shop-1',
        from: '2026-07-03',
        to: '2026-08-31',
        currency: 'USD',
      }),
    )
  })

  it('allows custom historical dates older than the rolling two-month window', async () => {
    const user = userEvent.setup()
    render(
      <AffiliateFilterBar
        enable60DayPreset
        filters={{ shopId: 'shop-1', from: '2026-05-01', to: '2026-05-07', currency: 'USD' }}
        latestAvailableDay="2026-08-31"
        loading={false}
        shops={[]}
        onChange={vi.fn()}
      />,
    )

    await user.click(screen.getAllByLabelText('日期范围')[0])

    expect(document.querySelector('td[title="2026-05-01"]')).not.toHaveClass('ant-picker-cell-disabled')
  })
})
