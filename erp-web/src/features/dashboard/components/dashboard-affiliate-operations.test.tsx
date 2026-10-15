import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DashboardAffiliateOperations as AffiliateData } from '../types/dashboard.types'
import { DashboardAffiliateOperations } from './dashboard-affiliate-operations'

Object.defineProperty(globalThis, 'ResizeObserver', {
  writable: true,
  value: class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({
    matches: false,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
  }),
})

const data: AffiliateData = {
  sampleFunnel: {
    scope: 'current_projection_all_time',
    applicationCount: 100,
    approvedCount: 60,
    shippedCount: 40,
    completedCount: 20,
    cancelledCount: 30,
    sourceObservedAt: '2026-09-21T00:00:00Z',
  },
  creatorLevels: [
    { level: 'L2', count: 12, share: 60 },
    { level: 'L1', count: 8, share: 40 },
  ],
  creatorEfficiency: {
    period: { start: '2026-08-21', end: '2026-09-19' },
    complete: true,
    shopCount: 1,
    totalCreators: 1,
    totalGmvMinor: 120000,
    rows: [
      {
        id: 'shop:creator',
        rank: 1,
        username: 'creator_one',
        avatarUrl: null,
        shopName: 'Demo Shop',
        videoCount: 4,
        gmvMinor: 120000,
        gmvPerVideoMinor: 30000,
        sampleStatus: 'SHIPPED',
        cumulativeGmvShare: 100,
      },
    ],
    pareto: [
      {
        id: 'shop:creator',
        username: 'creator_one',
        shopName: 'Demo Shop',
        gmvMinor: 120000,
        cumulativeGmvShare: 100,
      },
    ],
  },
}

describe('DashboardAffiliateOperations', () => {
  it('renders the sample funnel, creator levels, and creator Pareto data', () => {
    render(<DashboardAffiliateOperations currency="USD" data={data} />)

    expect(screen.getByText('样品状态漏斗')).toBeInTheDocument()
    expect(screen.getByText('L0–L7 达人等级分布')).toBeInTheDocument()
    expect(screen.getByText('达人效率与 GMV Pareto')).toBeInTheDocument()
    expect(screen.getByLabelText('达人GMV帕累托图')).toBeInTheDocument()
    expect(screen.getAllByText('@creator_one')).not.toHaveLength(0)
  })
})
