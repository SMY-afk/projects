import { useCallback, useEffect, useRef, useState } from 'react'
import { getAffiliateSyncErrorMessage } from '../affiliate-sync-error'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import type { AffiliateFilters } from '../components/affiliate-filter-bar'
import type { AffiliateCenterResource } from '../types/affiliate-center.types'

interface ScopedSyncMessage {
  windowKey: string
  type: 'success' | 'error'
  text: string
}

interface AutomaticRun {
  windowKey: string
  runId: string
}

function syncWindowKey(resource: AffiliateCenterResource, filters: AffiliateFilters) {
  return `${resource}:${filters.shopId}:${filters.from}:${filters.to}:${filters.currency}`
}

export function useAffiliateSync(
  filters: AffiliateFilters,
  resource: AffiliateCenterResource,
  onReload: () => void,
  captureProvider = 'HubStudio/CDP 浏览器',
) {
  const currentWindowKey = syncWindowKey(resource, filters)
  const currentWindowKeyRef = useRef(currentWindowKey)
  useEffect(() => {
    currentWindowKeyRef.current = currentWindowKey
  }, [currentWindowKey])
  const automaticSyncAttempts = useRef(new Map<string, number>())
  const inFlightWindows = useRef(new Set<string>())
  const [automaticRun, setAutomaticRun] = useState<AutomaticRun>()
  const [syncingWindowKey, setSyncingWindowKey] = useState<string>()
  const [scopedMessage, setScopedMessage] = useState<ScopedSyncMessage>()

  const submitSync = useCallback(
    async (targetResource: AffiliateCenterResource, automatic = false) => {
      if (!filters.shopId) {
        setScopedMessage({ windowKey: currentWindowKey, type: 'error', text: '请先选择店铺。' })
        return
      }
      const requestedFilters = { ...filters }
      const windowKey = syncWindowKey(targetResource, requestedFilters)
      const attempts = automaticSyncAttempts.current.get(windowKey) ?? 0
      if ((automatic && attempts >= 2) || inFlightWindows.current.has(windowKey)) return
      if (automatic) automaticSyncAttempts.current.set(windowKey, attempts + 1)
      inFlightWindows.current.add(windowKey)
      if (currentWindowKeyRef.current === windowKey) {
        setSyncingWindowKey(windowKey)
        setScopedMessage(undefined)
      }
      try {
        const response = await affiliateCenterApi.sync({ ...requestedFilters, resources: [targetResource] })
        if (currentWindowKeyRef.current !== windowKey) return
        if (automatic) {
          const intents = response.items.filter((item) => item.resource === targetResource)
          const pending = intents.filter((item) => item.status !== 'succeeded')
          const intent = pending[pending.length - 1] ?? intents[intents.length - 1]
          if (intent) setAutomaticRun({ windowKey, runId: intent.runId })
        }
        setScopedMessage({
          windowKey,
          type: 'success',
          text: automatic
            ? '所选日期缺少逐日快照，已只提交缺失日期；补齐后将自动显示汇总。'
            : '同步请求已提交，请在同步状态中查看进度。',
        })
        onReload()
      } catch (error) {
        if (currentWindowKeyRef.current !== windowKey) return
        setScopedMessage({
          windowKey,
          type: 'error',
          text: getAffiliateSyncErrorMessage(targetResource, error, captureProvider),
        })
      } finally {
        inFlightWindows.current.delete(windowKey)
        if (currentWindowKeyRef.current === windowKey) {
          setSyncingWindowKey((current) => (current === windowKey ? undefined : current))
        }
      }
    },
    [captureProvider, currentWindowKey, filters, onReload],
  )

  const handleSyncSettled = useCallback(() => {
    setAutomaticRun((current) => (current?.windowKey === currentWindowKey ? undefined : current))
    onReload()
  }, [currentWindowKey, onReload])

  const clearResolvedError = useCallback(() => {
    setScopedMessage((current) =>
      current?.windowKey === currentWindowKey && current.type === 'error' ? undefined : current,
    )
  }, [currentWindowKey])

  const clearResolvedSuccess = useCallback(() => {
    setScopedMessage((current) =>
      current?.windowKey === currentWindowKey && current.type === 'success' ? undefined : current,
    )
  }, [currentWindowKey])

  return {
    automaticRun,
    clearResolvedError,
    clearResolvedSuccess,
    currentWindowKey,
    handleSyncSettled,
    submitSync,
    syncing: syncingWindowKey === currentWindowKey,
    syncMessage: scopedMessage?.windowKey === currentWindowKey ? scopedMessage : undefined,
  }
}
