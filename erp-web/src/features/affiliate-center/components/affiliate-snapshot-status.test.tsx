import { render, screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import type { AffiliateResourceSyncStatus, AffiliateSyncRun } from '../types/affiliate-center.types'
import { AffiliateSnapshotStatus } from './affiliate-snapshot-status'

const completeRun: AffiliateSyncRun = {
  runId: 'run-1',
  status: 'succeeded',
  fetchedCount: 10,
  persistedCount: 10,
  startedAt: '2026-08-26T00:00:00Z',
  finishedAt: '2026-08-26T00:05:00Z',
  freshAt: '2026-08-26T00:05:00Z',
  errorCategory: null,
  errorSummary: null,
}

const syncStatus = (status: string, latestRun: AffiliateSyncRun = completeRun): AffiliateResourceSyncStatus => ({
  resource: 'videos',
  resourceType: 'affiliate_video',
  status,
  latestRun,
  lastFailureRun: null,
  lastCompleteRunId: status === 'succeeded' ? latestRun.runId : null,
  lastCompleteAt: status === 'succeeded' ? latestRun.finishedAt : null,
})

describe('AffiliateSnapshotStatus', () => {
  beforeAll(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-26T12:00:00Z'))
  })

  afterAll(() => vi.useRealTimers())

  it('shows data source, recent collection time, and complete state', () => {
    render(<AffiliateSnapshotStatus resource="videos" run={completeRun} status={syncStatus('succeeded')} />)

    expect(screen.getByText('数据来源')).toBeInTheDocument()
    expect(screen.getByText('浏览器监听同步')).toBeInTheDocument()
    expect(screen.getByText('最近采集时间')).toBeInTheDocument()
    expect(screen.getByText('完整 · 10 / 10 条')).toBeInTheDocument()
  })

  it('shows partial when the latest resource run is incomplete', () => {
    const partialRun = { ...completeRun, runId: 'run-2', status: 'partial', persistedCount: 7 }
    render(<AffiliateSnapshotStatus resource="videos" status={syncStatus('partial', partialRun)} />)

    expect(screen.getByText('部分 · 7 / 10 条')).toBeInTheDocument()
  })

  it('labels browser export synchronization explicitly', () => {
    render(
      <AffiliateSnapshotStatus
        resource="videos"
        run={{ ...completeRun, sourceKind: 'browser_export' }}
        status={syncStatus('succeeded')}
      />,
    )

    expect(screen.getByText('浏览器导出同步')).toBeInTheDocument()
  })

  it('marks a complete snapshot stale after 24 hours without collection', () => {
    const staleRun = {
      ...completeRun,
      finishedAt: '2026-08-24T00:05:00Z',
      freshAt: '2026-08-24T00:05:00Z',
    }
    render(<AffiliateSnapshotStatus resource="videos" run={staleRun} status={syncStatus('succeeded', staleRun)} />)

    expect(screen.getByText('陈旧 · 10 / 10 条')).toBeInTheDocument()
  })
})
