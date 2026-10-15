import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, DatePicker, Empty, Segmented, Select, Space, Tabs, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { AFFILIATE_REFRESH_INTERVAL_MS } from '../affiliate-refresh'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import { AffiliateLiveAccountTable } from '../components/affiliate-live-account-table'
import { affiliateCenterTabs, type AffiliateCenterTab } from '../components/affiliate-center-tabs'
import type {
  AffiliateLiveAccountMetric,
  AffiliateLiveRangePreset,
  AffiliateLiveSortBy,
  AffiliateLiveSortOrder,
} from '../types/affiliate-live-account.types'
import type { AffiliateShop } from '../types/affiliate-center.types'
import './affiliate-center-page.css'

const rangeOptions: Array<{ label: string; value: AffiliateLiveRangePreset }> = [
  { label: '今天', value: 'today' },
  { label: '近 7 天', value: 'last7d' },
  { label: '近 1 个月', value: 'last30d' },
  { label: '近 2 个月', value: 'last60d' },
  { label: '自定义', value: 'custom' },
]

const readPreset = (search: string): AffiliateLiveRangePreset => {
  const value = new URLSearchParams(search).get('livePreset')
  return rangeOptions.some((option) => option.value === value) ? (value as AffiliateLiveRangePreset) : 'last7d'
}

export default function AffiliateLiveAccountPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const [shops, setShops] = useState<AffiliateShop[]>([])
  const [rows, setRows] = useState<AffiliateLiveAccountMetric[]>([])
  const [shopsLoading, setShopsLoading] = useState(true)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string>()
  const [notice, setNotice] = useState<string>()
  const [freshnessAsOf, setFreshnessAsOf] = useState<string | null>()
  const [sortBy, setSortBy] = useState<AffiliateLiveSortBy>('gmv')
  const [sortOrder, setSortOrder] = useState<AffiliateLiveSortOrder>('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [total, setTotal] = useState(0)
  const refreshTimers = useRef<number[]>([])
  const requestedShopId = useMemo(() => new URLSearchParams(location.search).get('shopId') ?? '', [location.search])
  const preset = useMemo(() => readPreset(location.search), [location.search])
  const customFrom = useMemo(() => new URLSearchParams(location.search).get('customFrom') ?? '', [location.search])
  const customTo = useMemo(() => new URLSearchParams(location.search).get('customTo') ?? '', [location.search])
  const customRange = useMemo<[Dayjs, Dayjs] | null>(() => {
    const from = dayjs(customFrom)
    const to = dayjs(customTo)
    return customFrom && customTo && from.isValid() && to.isValid() ? [from, to] : null
  }, [customFrom, customTo])
  const hasCompleteRange = preset !== 'custom' || customRange !== null
  const selectedShop = shops.find((shop) => shop.id === requestedShopId) ?? shops[0]

  useEffect(() => {
    let active = true
    affiliateCenterApi
      .listShops()
      .then((result) => active && setShops(result))
      .catch(() => active && setError('联盟店铺读取失败，请稍后重试。'))
      .finally(() => active && setShopsLoading(false))
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!selectedShop || selectedShop.id === requestedShopId) return
    const search = new URLSearchParams(location.search)
    search.set('shopId', selectedShop.id)
    void navigate({ pathname: location.pathname, search: `?${search}` }, { replace: true })
  }, [location.pathname, location.search, navigate, requestedShopId, selectedShop])

  const load = useCallback(async () => {
    if (!selectedShop) return
    if (!hasCompleteRange) {
      setRows([])
      setFreshnessAsOf(undefined)
      return
    }
    setLoading(true)
    setError(undefined)
    try {
      const result = await affiliateCenterApi.listLiveAccounts({
        shopId: selectedShop.id,
        page,
        pageSize,
        preset,
        ...(preset === 'custom' ? { customFrom, customTo } : {}),
        sortBy,
        sortOrder,
      })
      setRows(result.data)
      setFreshnessAsOf(result.freshness.asOf)
      setTotal(result.pagination.total)
    } catch {
      setRows([])
      setError('联盟账号直播数据读取失败。未回退到 Mock，请检查店铺和同步状态。')
    } finally {
      setLoading(false)
    }
  }, [customFrom, customTo, hasCompleteRange, page, pageSize, preset, selectedShop, sortBy, sortOrder])

  useEffect(() => () => refreshTimers.current.forEach((timer) => window.clearTimeout(timer)), [])

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timeout)
  }, [load])

  useEffect(() => {
    if (!selectedShop || !hasCompleteRange) return
    const interval = window.setInterval(() => void load(), AFFILIATE_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(interval)
  }, [hasCompleteRange, load, selectedShop])

  const selectShop = (shopId: string) => {
    setPage(1)
    const search = new URLSearchParams(location.search)
    search.set('shopId', shopId)
    void navigate({ pathname: location.pathname, search: `?${search}` }, { replace: true })
  }

  const selectPreset = (nextPreset: AffiliateLiveRangePreset) => {
    setPage(1)
    const search = new URLSearchParams(location.search)
    search.set('livePreset', nextPreset)
    void navigate({ pathname: location.pathname, search: `?${search}` }, { replace: true })
  }

  const selectCustomRange = (range: [Dayjs, Dayjs]) => {
    setPage(1)
    const search = new URLSearchParams(location.search)
    search.set('livePreset', 'custom')
    search.set('customFrom', range[0].format('YYYY-MM-DD'))
    search.set('customTo', range[1].format('YYYY-MM-DD'))
    void navigate({ pathname: location.pathname, search: `?${search}` }, { replace: true })
  }

  const syncLatest = async () => {
    if (!selectedShop || !hasCompleteRange) return
    setSyncing(true)
    setError(undefined)
    setNotice(undefined)
    try {
      const result = await affiliateCenterApi.syncLiveAccounts({
        shopId: selectedShop.id,
        preset,
        ...(preset === 'custom' ? { customFrom, customTo } : {}),
      })
      const queued = result.items.filter((item) => !item.existing).length
      setNotice(
        queued > 0
          ? `同步任务已提交（${result.items.length} 个时间窗口），正在获取 TikTok 最新可用数据。`
          : '相同时间范围的同步任务已在处理中，稍后会自动刷新。',
      )
      await load()
      refreshTimers.current.forEach((timer) => window.clearTimeout(timer))
      refreshTimers.current = [3_000, 8_000].map((delay) => window.setTimeout(() => void load(), delay))
    } catch {
      setError('联盟账号直播数据同步提交失败，请检查店铺授权和同步权限。')
    } finally {
      setSyncing(false)
    }
  }

  const freshnessLabel = freshnessAsOf
    ? new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'medium',
        timeStyle: 'medium',
        timeZone: selectedShop?.timezone ?? undefined,
      }).format(new Date(freshnessAsOf))
    : '尚未同步'

  return (
    <Space className="affiliate-center-page" orientation="vertical" size="large">
      <div className="affiliate-center-header">
        <div>
          <Typography.Title level={2}>联盟中心</Typography.Title>
          <Typography.Text type="secondary">复用同步后的直播底层数据，仅展示联盟账号。</Typography.Text>
        </div>
        <Button
          icon={<ReloadOutlined />}
          loading={syncing}
          disabled={!selectedShop || !hasCompleteRange}
          onClick={() => void syncLatest()}
        >
          同步最新数据
        </Button>
      </div>
      <Tabs
        activeKey="live-accounts"
        items={affiliateCenterTabs}
        onChange={(key) => {
          const target = key as AffiliateCenterTab
          void navigate({ pathname: `/affiliate-center/${target}`, search: location.search })
        }}
      />
      <Card size="small">
        <Space className="affiliate-filter-bar" size="middle" wrap>
          <label className="affiliate-filter-field">
            <Typography.Text type="secondary">店铺</Typography.Text>
            <Select
              aria-label="店铺"
              loading={shopsLoading}
              value={selectedShop?.id}
              options={shops.map((shop) => ({ value: shop.id, label: shop.shopName }))}
              onChange={selectShop}
            />
          </label>
          <label className="affiliate-filter-field">
            <Typography.Text type="secondary">日期范围</Typography.Text>
            <Segmented<AffiliateLiveRangePreset>
              aria-label="日期范围"
              options={rangeOptions}
              value={preset}
              onChange={selectPreset}
            />
            {preset === 'custom' && (
              <Space orientation="vertical" size={0}>
                <DatePicker.RangePicker
                  aria-label="自定义日期范围"
                  allowClear={false}
                  maxDate={dayjs()}
                  value={customRange}
                  disabledDate={(current) => current.isAfter(dayjs(), 'day')}
                  onChange={(value) => value?.[0] && value[1] && selectCustomRange([value[0], value[1]])}
                />
                <Typography.Text type="secondary">可查询任意历史日期，不能包含未来日期</Typography.Text>
              </Space>
            )}
          </label>
        </Space>
      </Card>
      {error && <Alert showIcon type="error" title={error} />}
      {notice && <Alert showIcon type="info" title={notice} />}
      {!shopsLoading && !shops.length ? (
        <Empty description="当前租户没有可用店铺" />
      ) : (
        <Card
          title="联盟账号直播数据"
          extra={<Typography.Text type="secondary">本地数据更新：{freshnessLabel}</Typography.Text>}
        >
          <AffiliateLiveAccountTable
            rows={rows}
            loading={loading}
            timezone={selectedShop?.timezone}
            sortBy={sortBy}
            sortOrder={sortOrder}
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={(nextPage, nextPageSize) => {
              setPage(nextPageSize === pageSize ? nextPage : 1)
              setPageSize(nextPageSize)
            }}
            onSortChange={(nextSortBy, nextSortOrder) => {
              setPage(1)
              setSortBy(nextSortBy)
              setSortOrder(nextSortOrder)
            }}
          />
        </Card>
      )}
    </Space>
  )
}
