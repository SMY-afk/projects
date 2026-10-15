import { useEffect, useRef, useState } from 'react'
import { AFFILIATE_REFRESH_INTERVAL_MS } from '../affiliate-refresh'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import type {
  AffiliateBrowserHealth,
  AffiliateBrowserHealthState,
  AffiliateCenterResource,
  AffiliateResourceSyncStatus,
  AffiliateSyncRun,
} from '../types/affiliate-center.types'

const ACTIVE_STATUSES = new Set(['queued', 'running', 'retry_wait'])
const FAILURE_STATUSES = new Set(['partial', 'failed', 'dead_letter'])
const FAILURE_REASONS: Record<string, string> = {
  session_expired: 'TikTok 登录已失效，请重新登录。',
  captcha: 'TikTok 要求完成 CAPTCHA 验证。',
  http_403: 'TikTok 返回 403，当前会话无权读取该页面。',
  rate_limited: 'TikTok 返回 429，采集已限流。',
  target_page_missing: '未能打开 TikTok 联盟中心达人页。',
  window_not_settable: 'TikTok 页面无法设置目标日期范围。',
  window_mismatch: 'TikTok 页面日期范围与 ERP 任务不一致。',
  request_timeout: 'TikTok 页面请求超时。',
  payload_structure_changed: 'TikTok 达人数据结构发生变化。',
  page_failed: '达人分页采集或持久化失败。',
}

function failureRun(status: AffiliateResourceSyncStatus): AffiliateSyncRun | null {
  if (FAILURE_STATUSES.has(status.status)) return status.latestRun
  if (ACTIVE_STATUSES.has(status.status)) return status.lastFailureRun
  return null
}

export function affiliateFailureMessage(status?: AffiliateResourceSyncStatus): string | undefined {
  if (!status) return undefined
  const run = failureRun(status)
  if (!run) return undefined
  const reason = FAILURE_REASONS[run.errorCategory ?? ''] ?? run.errorSummary ?? '未知错误。'
  return ACTIVE_STATUSES.has(status.status) ? `正在自动重试。上次失败：${reason}` : `同步失败：${reason}`
}

export function affiliateBrowserMessage(
  health?: AffiliateBrowserHealth,
  captureProvider = 'HubStudio/CDP 浏览器',
): string | undefined {
  if (!health || health.state === 'online') return undefined
  const messages: Record<Exclude<AffiliateBrowserHealthState, 'online'>, string> = {
    browser_offline: `${captureProvider}离线；已有完整快照仍可查询，新增数据将等待监听恢复。`,
    connecting: `正在连接${captureProvider}。`,
    session_expired: `TikTok 登录已失效，请在${captureProvider}中重新登录；恢复后会自动补跑当天任务。`,
    captcha: `TikTok 要求完成验证码，请在${captureProvider}中人工完成；通过后会自动补跑当天任务。`,
  }
  return messages[health.state]
}

export function affiliateLatestAvailableDay(
  health: AffiliateBrowserHealth,
  resource: AffiliateCenterResource,
): string | undefined {
  if (health.state === 'connecting') return undefined
  return health.latestAvailableDates?.[resource] ?? health.latestAvailableDate ?? undefined
}

interface AffiliateLatestDayObservation {
  shopId: string
  resource: AffiliateCenterResource
  day: string | undefined
}

export function affiliateCurrentLatestAvailableDay(
  observation: AffiliateLatestDayObservation | undefined,
  shopId: string,
  resource: AffiliateCenterResource,
): string | undefined {
  if (observation?.shopId !== shopId || observation.resource !== resource) return undefined
  return observation.day
}

export function useAffiliateSyncStatus(
  shopId: string,
  resource: AffiliateCenterResource,
  refreshToken: number,
  onSettled: () => void,
  trackedRunId?: string,
  captureProvider = 'HubStudio/CDP 浏览器',
) {
  const [statusError, setStatusError] = useState<string>()
  const [failureMessage, setFailureMessage] = useState<string>()
  const [browserMessage, setBrowserMessage] = useState<string>()
  const [browserState, setBrowserState] = useState<AffiliateBrowserHealthState>()
  const [latestDayObservation, setLatestDayObservation] = useState<AffiliateLatestDayObservation>()
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>()
  const notifiedRuns = useRef(new Set<string>())

  useEffect(() => {
    if (!shopId) return
    let active = true
    let timer: number | undefined
    let observedActiveRun = false
    const poll = async () => {
      try {
        const response = await affiliateCenterApi.getSyncStatus(shopId)
        if (!active) return
        setStatusError(undefined)
        const items = response.items
        const current = items.find((item) => item.resource === resource)
        setLastUpdatedAt(
          current?.latestRun?.freshAt ??
            current?.latestRun?.finishedAt ??
            current?.lastCompleteAt ??
            response.browser?.updatedAt ??
            undefined,
        )
        setBrowserMessage(affiliateBrowserMessage(response.browser ?? undefined, captureProvider))
        setBrowserState(response.browser?.state)
        setLatestDayObservation({
          shopId,
          resource,
          day:
            response.latestAvailableDates?.[resource] ??
            (response.browser ? affiliateLatestAvailableDay(response.browser, resource) : undefined),
        })
        const trackedRun = trackedRunId
          ? [current?.latestRun, current?.lastFailureRun].find((run) => run?.runId === trackedRunId)
          : undefined
        if (trackedRunId) {
          if (!trackedRun) {
            timer = window.setTimeout(() => void poll(), 500)
            return
          }
          if (ACTIVE_STATUSES.has(trackedRun.status)) {
            setFailureMessage(affiliateFailureMessage(current))
            timer = window.setTimeout(() => void poll(), 2_000)
            return
          }
          const trackedStatus = current ? { ...current, status: trackedRun.status, latestRun: trackedRun } : undefined
          setFailureMessage(affiliateFailureMessage(trackedStatus))
          if (!notifiedRuns.current.has(trackedRun.runId)) {
            notifiedRuns.current.add(trackedRun.runId)
            onSettled()
          }
          return
        }
        setFailureMessage(affiliateFailureMessage(current))
        if (current && ACTIVE_STATUSES.has(current.status)) {
          observedActiveRun = true
          timer = window.setTimeout(() => void poll(), 2_000)
        } else if (observedActiveRun) {
          onSettled()
        } else {
          timer = window.setTimeout(() => void poll(), AFFILIATE_REFRESH_INTERVAL_MS)
        }
      } catch {
        if (active) {
          setStatusError('同步状态读取失败，未回退到 Mock。')
          timer = window.setTimeout(() => void poll(), AFFILIATE_REFRESH_INTERVAL_MS)
        }
      }
    }
    void poll()
    return () => {
      active = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [captureProvider, onSettled, refreshToken, resource, shopId, trackedRunId])

  const latestAvailableDay = affiliateCurrentLatestAvailableDay(latestDayObservation, shopId, resource)
  return { browserMessage, browserState, failureMessage, lastUpdatedAt, latestAvailableDay, statusError }
}
