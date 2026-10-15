import { SyncOutlined } from '@ant-design/icons'
import { Alert, Button, Space, Tabs, Typography } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { AFFILIATE_REFRESH_INTERVAL_MS } from '../affiliate-refresh'
import { formatAffiliateLastUpdatedAt } from '../affiliate-last-updated'
import {
  affiliateRollingPresetForRange,
  hasAffiliateDateQuery,
  hasCompleteAffiliateFilterQuery,
  readAffiliateFilters,
  switchAffiliateResourceSearch,
  type AffiliateRollingPreset,
  writeAffiliateFilterSearch,
} from '../affiliate-filter-query'
import { currentTikTokAffiliateDate, resolveAffiliateLatestAvailableDay } from '../affiliate-available-date'
import { isAffiliateAvailabilityErrorResolved } from '../affiliate-sync-error'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import { AffiliateFilterBar, type AffiliateFilters } from '../components/affiliate-filter-bar'
import { AffiliateLocalExportButton } from '../components/affiliate-local-export-button'
import { AffiliateRangeSummary } from '../components/affiliate-range-summary'
import { AffiliateResourceTables } from '../components/affiliate-resource-tables'
import { affiliateCenterTabs, type AffiliateCenterTab } from '../components/affiliate-center-tabs'
import { useAffiliateDateWindow } from '../hooks/use-affiliate-date-window'
import { useAffiliateSync } from '../hooks/use-affiliate-sync'
import { useAffiliateSyncStatus } from '../hooks/use-affiliate-sync-status'
import type {
  AffiliateCenterResource,
  AffiliateResourceContract,
  AffiliateShop,
  AffiliateStableCreatorPage,
  AffiliateVideoPage,
} from '../types/affiliate-center.types'
import './affiliate-center-page.css'

export default function AffiliateCenterPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const resource: AffiliateCenterResource = location.pathname.endsWith('/videos') ? 'videos' : 'creators'
  const filters = useMemo(() => readAffiliateFilters(location.search, resource), [location.search, resource])
  const [contract, setContract] = useState<AffiliateResourceContract>()
  const [shops, setShops] = useState<AffiliateShop[]>([])
  const [creatorPage, setCreatorPage] = useState<AffiliateStableCreatorPage>()
  const [videoPage, setVideoPage] = useState<AffiliateVideoPage>()
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [shopsLoading, setShopsLoading] = useState(true)
  const [reloadToken, setReloadToken] = useState(0)
  const [baseError, setBaseError] = useState<string>()
  const [dataError, setDataError] = useState<string>()
  const requestSequence = useRef(0)
  const loadedScope = useRef<string | undefined>(undefined)
  const reloadVisibleData = useCallback(() => setReloadToken((value) => value + 1), [])
  const selectedShop = shops.find((shop) => shop.id === filters.shopId)
  const captureProvider = selectedShop?.shopName === 'Akeleo Toys' ? '紫鸟浏览器' : 'HubStudio/CDP 浏览器'
  const {
    automaticRun,
    clearResolvedError,
    clearResolvedSuccess,
    currentWindowKey,
    handleSyncSettled,
    submitSync,
    syncing,
    syncMessage,
  } = useAffiliateSync(filters, resource, reloadVisibleData, captureProvider)
  const {
    browserMessage,
    browserState,
    failureMessage,
    latestAvailableDay: reportedLatestAvailableDay,
    statusError,
  } = useAffiliateSyncStatus(
    filters.shopId,
    resource,
    reloadToken,
    handleSyncSettled,
    automaticRun?.windowKey === currentWindowKey ? automaticRun.runId : undefined,
    captureProvider,
  )
  const latestAvailableDay = selectedShop
    ? resolveAffiliateLatestAvailableDay(reportedLatestAvailableDay)
    : reportedLatestAvailableDay
  const tikTokToday = selectedShop ? currentTikTokAffiliateDate(selectedShop.timezone) : undefined
  const hasCompleteSnapshot = resource === 'creators' ? creatorPage?.report != null : videoPage?.run != null
  const visibleUpdatedAt = hasCompleteSnapshot
    ? resource === 'creators'
      ? (creatorPage?.report?.capturedAt ?? creatorPage?.report?.importedAt)
      : (videoPage?.run?.freshAt ?? videoPage?.run?.finishedAt)
    : undefined
  const writeFilters = useCallback(
    (nextFilters: AffiliateFilters, replace = true, rollingPreset?: AffiliateRollingPreset | false) => {
      const search = writeAffiliateFilterSearch(location.search, resource, nextFilters, rollingPreset)
      void navigate({ pathname: location.pathname, search: `?${search}` }, { replace })
    },
    [location.pathname, location.search, navigate, resource],
  )
  const handleFilterChange = useCallback(
    (nextFilters: AffiliateFilters) => {
      const rollingPreset = latestAvailableDay
        ? affiliateRollingPresetForRange(nextFilters, latestAvailableDay)
        : undefined
      writeFilters(nextFilters, true, rollingPreset ?? false)
    },
    [latestAvailableDay, writeFilters],
  )
  useAffiliateDateWindow(filters, latestAvailableDay, location.search, resource, writeFilters)
  useEffect(() => {
    if ((browserState && browserState !== 'online') || !latestAvailableDay || filters.to > latestAvailableDay) return
    const timeout = window.setTimeout(() => clearResolvedError(), 0)
    return () => window.clearTimeout(timeout)
  }, [browserState, clearResolvedError, filters.to, latestAvailableDay])
  useEffect(() => {
    let active = true
    Promise.all([affiliateCenterApi.listResources(), affiliateCenterApi.listShops()])
      .then(([nextContract, nextShops]) => {
        if (!active) return
        setContract(nextContract)
        setShops(nextShops)
        setBaseError(undefined)
      })
      .catch(() => active && setBaseError('联盟中心基础数据读取失败。未回退到 Mock。'))
      .finally(() => active && setShopsLoading(false))
    return () => {
      active = false
    }
  }, [])
  useEffect(() => {
    if (!shops.length) return
    const selected = shops.find((shop) => shop.id === filters.shopId) ?? shops[0]
    if (selected.id !== filters.shopId) {
      const params = new URLSearchParams(location.search)
      params.set('shopId', selected.id)
      if (!params.has('currency')) params.set('currency', selected.currency ?? filters.currency)
      void navigate({ pathname: location.pathname, search: `?${params}` }, { replace: true })
      return
    }
    if (selected.id === filters.shopId && hasCompleteAffiliateFilterQuery(location.search, resource)) return
    const hasDates = hasAffiliateDateQuery(location.search, resource)
    if (!hasDates && !latestAvailableDay) return
    const latestDay = latestAvailableDay ?? filters.to
    writeFilters(
      {
        ...filters,
        shopId: selected.id,
        from: hasDates ? filters.from : dayjs(latestDay).subtract(6, 'day').format('YYYY-MM-DD'),
        to: hasDates ? filters.to : latestDay,
        currency: new URLSearchParams(location.search).has('currency')
          ? filters.currency
          : (selected.currency ?? filters.currency),
      },
      true,
      hasDates ? false : 'last7d',
    )
  }, [filters, latestAvailableDay, location.pathname, location.search, navigate, resource, shops, writeFilters])
  const loadPage = useCallback(
    async (nextPage: number) => {
      if (!filters.shopId || !hasCompleteAffiliateFilterQuery(location.search, resource)) return
      const sequence = ++requestSequence.current
      await Promise.resolve()
      if (sequence !== requestSequence.current) return
      setLoading(true)
      setDataError(undefined)
      const query = { ...filters, page: nextPage, pageSize: 50 }
      const requestScope = `${resource}:${filters.shopId}:${filters.from}:${filters.to}:${filters.currency}`
      try {
        if (resource === 'creators') {
          const result = await affiliateCenterApi.listCreatorMetrics({
            ...query,
            sort: 'affiliateGmvMinor',
            order: 'desc',
          })
          if (sequence === requestSequence.current) {
            setCreatorPage(result)
            loadedScope.current = requestScope
            if (nextPage === 1 && result.report === null) {
              void submitSync('creators', true)
            } else if (result.report !== null) {
              clearResolvedSuccess()
            }
          }
        } else {
          const result = await affiliateCenterApi.listVideos({ ...query, sort: 'gmvMinor', order: 'desc' })
          if (sequence === requestSequence.current) {
            setVideoPage(result)
            loadedScope.current = requestScope
            if (nextPage === 1 && result.run === null) void submitSync('videos', true)
            else if (result.run !== null) clearResolvedSuccess()
          }
        }
        if (sequence === requestSequence.current) setPage(nextPage)
      } catch {
        if (sequence !== requestSequence.current) return
        if (loadedScope.current !== requestScope) {
          if (resource === 'creators') setCreatorPage(undefined)
          else setVideoPage(undefined)
        }
        setDataError(
          `${resource === 'creators' ? '达人' : '所有视频'}真实数据读取失败。未回退到 Mock，请检查登录会话、店铺和日期范围。`,
        )
      } finally {
        if (sequence === requestSequence.current) setLoading(false)
      }
    },
    [clearResolvedSuccess, filters, location.search, resource, submitSync],
  )

  useEffect(() => {
    const timeout = window.setTimeout(() => void loadPage(1), 0)
    return () => window.clearTimeout(timeout)
  }, [loadPage, reloadToken])

  useEffect(() => {
    if (!filters.shopId) return
    const interval = window.setInterval(() => setReloadToken((value) => value + 1), AFFILIATE_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [filters.shopId, resource])

  const handleSync = async () => submitSync(resource)
  const visibleSyncMessage =
    syncMessage?.type === 'error' &&
    isAffiliateAvailabilityErrorResolved(syncMessage.text, filters.to, latestAvailableDay)
      ? undefined
      : syncMessage

  return (
    <Space className="affiliate-center-page" orientation="vertical" size="large">
      <div className="affiliate-center-header">
        <div>
          <Typography.Title level={2}>联盟中心</Typography.Title>
          <Typography.Text type="secondary">筛选条件保存在链接中；达人与视频只展示真实完整快照。</Typography.Text>
          <br />
          <Typography.Text type="secondary">
            所选范围完整快照更新时间：
            {formatAffiliateLastUpdatedAt(visibleUpdatedAt ?? undefined, selectedShop?.timezone)}
          </Typography.Text>
          {latestAvailableDay && (
            <>
              <br />
              <Typography.Text type="secondary">当前已知可查询至：{latestAvailableDay}</Typography.Text>
            </>
          )}
        </div>
        <Space wrap>
          <AffiliateLocalExportButton
            disabled={!hasCompleteAffiliateFilterQuery(location.search, resource)}
            from={filters.from}
            to={filters.to}
          />
          <Button
            disabled={!filters.shopId}
            icon={<SyncOutlined />}
            loading={syncing}
            onClick={() => void handleSync()}
            type="primary"
          >
            {resource === 'creators' ? '同步联盟达人' : '同步所有视频'}
          </Button>
        </Space>
      </div>
      <Tabs
        activeKey={resource}
        items={affiliateCenterTabs}
        onChange={(key) => {
          const target = key as AffiliateCenterTab
          if (target === 'live-accounts') {
            void navigate({ pathname: '/affiliate-center/live-accounts', search: location.search })
            return
          }
          const search = switchAffiliateResourceSearch(location.search, resource, filters, target)
          void navigate({ pathname: `/affiliate-center/${target}`, search: `?${search}` })
        }}
      />
      {baseError && <Alert showIcon type="error" title={baseError} />}
      <AffiliateFilterBar
        dateRangeLabel={resource === 'videos' ? '统计日期（非发布时间）' : undefined}
        enable60DayPreset
        filters={filters}
        latestAvailableDay={latestAvailableDay}
        loading={shopsLoading}
        shops={shops}
        tikTokToday={tikTokToday}
        onChange={handleFilterChange}
      />
      {visibleSyncMessage && <Alert showIcon type={visibleSyncMessage.type} title={visibleSyncMessage.text} />}
      {browserMessage && (
        <Alert
          showIcon
          type={browserState === 'connecting' ? 'info' : browserState === 'browser_offline' ? 'warning' : 'error'}
          title={browserMessage}
        />
      )}
      {statusError && <Alert showIcon type="error" title={statusError} />}
      {failureMessage && !hasCompleteSnapshot && <Alert showIcon type="error" title={failureMessage} />}
      {dataError && (
        <Alert
          showIcon
          type="error"
          title={dataError}
          action={<Button onClick={() => void loadPage(page)}>重试</Button>}
        />
      )}
      <AffiliateRangeSummary
        currency={filters.currency}
        from={filters.from}
        loading={loading}
        resource={resource}
        summary={
          hasCompleteSnapshot ? (resource === 'creators' ? creatorPage?.summary : videoPage?.summary) : undefined
        }
        to={filters.to}
      />
      <AffiliateResourceTables
        creatorPage={creatorPage}
        currency={filters.currency}
        loading={loading}
        metricDefinitions={contract?.display.creators.metrics}
        page={page}
        resource={resource}
        shopName={selectedShop?.shopName}
        videoPage={videoPage}
        onPageChange={(nextPage) => void loadPage(nextPage)}
        onCreatorOpen={(creatorId) =>
          void navigate({
            pathname: `/affiliate-center/creators/${creatorId}`,
            search: `?${writeAffiliateFilterSearch(location.search, resource, filters)}`,
          })
        }
      />
    </Space>
  )
}
