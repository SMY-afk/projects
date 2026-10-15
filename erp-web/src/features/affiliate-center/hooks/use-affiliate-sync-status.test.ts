import { describe, expect, it } from 'vitest'
import type { AffiliateResourceSyncStatus, AffiliateSyncRun } from '../types/affiliate-center.types'
import {
  affiliateBrowserMessage,
  affiliateCurrentLatestAvailableDay,
  affiliateFailureMessage,
  affiliateLatestAvailableDay,
} from './use-affiliate-sync-status'

const failedRun = (category: string): AffiliateSyncRun => ({
  runId: 'failed-run',
  status: 'failed',
  fetchedCount: 0,
  persistedCount: 0,
  startedAt: '2026-08-27T01:00:00Z',
  finishedAt: '2026-08-27T01:01:00Z',
  freshAt: null,
  errorCategory: category,
  errorSummary: null,
})

const status = (
  state: string,
  latestRun: AffiliateSyncRun | null,
  lastFailureRun: AffiliateSyncRun | null,
): AffiliateResourceSyncStatus => ({
  resource: 'creators',
  resourceType: 'affiliate_creator',
  status: state,
  latestRun,
  lastFailureRun,
  lastCompleteRunId: null,
  lastCompleteAt: null,
})

describe('affiliateFailureMessage', () => {
  it('shows the real login failure reason', () => {
    expect(affiliateFailureMessage(status('failed', failedRun('session_expired'), null))).toBe(
      '同步失败：TikTok 登录已失效，请重新登录。',
    )
  })

  it('keeps the previous CAPTCHA reason visible while retrying', () => {
    expect(affiliateFailureMessage(status('queued', null, failedRun('captcha')))).toBe(
      '正在自动重试。上次失败：TikTok 要求完成 CAPTCHA 验证。',
    )
  })

  it('shows HTTP 403 and 429 categories without a mock fallback', () => {
    expect(affiliateFailureMessage(status('partial', failedRun('http_403'), null))).toContain('403')
    expect(affiliateFailureMessage(status('failed', failedRun('rate_limited'), null))).toContain('429')
  })
})

describe('affiliateBrowserMessage', () => {
  it('explains login recovery and automatic catch-up', () => {
    expect(
      affiliateBrowserMessage({
        state: 'session_expired',
        cdpAvailable: true,
        sessionAvailable: false,
        updatedAt: '2026-08-28T01:00:00Z',
        recoveredAt: null,
        latestAvailableDate: '2026-08-29',
      }),
    ).toContain('恢复后会自动补跑当天任务')
  })

  it('does not show a warning while the browser session is online', () => {
    expect(
      affiliateBrowserMessage({
        state: 'online',
        cdpAvailable: true,
        sessionAvailable: true,
        updatedAt: '2026-08-28T01:00:00Z',
        recoveredAt: null,
        latestAvailableDate: '2026-08-29',
      }),
    ).toBeUndefined()
  })

  it('names the Purple Bird listener for Akeleo Toys', () => {
    expect(
      affiliateBrowserMessage(
        {
          state: 'browser_offline',
          cdpAvailable: false,
          sessionAvailable: false,
          updatedAt: '2026-09-04T01:00:00Z',
          recoveredAt: null,
          latestAvailableDate: null,
        },
        '紫鸟浏览器',
      ),
    ).toContain('紫鸟浏览器')
  })
})

describe('affiliateLatestAvailableDay', () => {
  const health = {
    state: 'online' as const,
    cdpAvailable: true,
    sessionAvailable: true,
    updatedAt: '2026-08-31T01:00:00Z',
    recoveredAt: null,
    latestAvailableDate: '2026-08-27',
    latestAvailableDates: { creators: '2026-08-29', videos: '2026-08-27' },
  }

  it('returns the TikTok latest day for the active resource', () => {
    expect(affiliateLatestAvailableDay(health, 'creators')).toBe('2026-08-29')
    expect(affiliateLatestAvailableDay(health, 'videos')).toBe('2026-08-27')
  })

  it('does not treat an old day as current while HubStudio is reconnecting', () => {
    expect(affiliateLatestAvailableDay({ ...health, state: 'connecting' }, 'creators')).toBeUndefined()
  })
})

describe('affiliateCurrentLatestAvailableDay', () => {
  const videoObservation = {
    shopId: 'shop-1',
    resource: 'videos' as const,
    day: '2026-08-29',
  }

  it('only exposes the latest day to the matching shop and resource', () => {
    expect(affiliateCurrentLatestAvailableDay(videoObservation, 'shop-1', 'videos')).toBe('2026-08-29')
    expect(affiliateCurrentLatestAvailableDay(videoObservation, 'shop-1', 'creators')).toBeUndefined()
    expect(affiliateCurrentLatestAvailableDay(videoObservation, 'shop-2', 'videos')).toBeUndefined()
  })
})
