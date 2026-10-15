import { useMemo, useState } from 'react'
import { ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, DatePicker, Empty, Select, Space, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { isDataMock } from '../api/data.api'
import { shopIsInDataRollout, type DataRolloutConfig } from '../config/data-rollout'
import { ContentRankingTable, MetricCards, TrendCard } from '../components/data-dashboard-sections'
import { DataStatusCard } from '../components/data-status-card'
import { resyncErrorMessage } from '../components/resync-error-message'
import { VideoRangeControls } from '../components/video-range-controls'
import { VideoRangeSummary } from '../components/video-range-summary'
import {
  useDataShopOptionsQuery,
  useLivesQuery,
  useOverviewQuery,
  useResyncMutation,
  useSyncStatusQuery,
  useSyncHealthQuery,
  useTrendsQuery,
  useVideosQuery,
} from '../queries/data.queries'
import { useShopLocalToday } from '../hooks/use-shop-local-today'
import type { ContentSort, VideoRangePreset } from '../types/data.types'
import { resolveVideoRange } from '../utils/video-range'
import DataUnavailablePage from './data-unavailable-page'
import './data-page.css'

const { RangePicker } = DatePicker

export default function DataPage({ rollout }: { rollout: DataRolloutConfig }) {
  const { hasPermissions } = useAuth()
  const shops = useDataShopOptionsQuery()
  const [shopId, setShopId] = useState<string>()
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(29, 'day'), dayjs()])
  const [granularity, setGranularity] = useState<'day' | 'hour'>('day')
  const [currency, setCurrency] = useState('USD')
  const [videoSort, setVideoSort] = useState<ContentSort>({ sortBy: 'gmv', sortOrder: 'desc' })
  const [videoRangePreset, setVideoRangePreset] = useState<VideoRangePreset>('last30d')
  const [videoCustomRange, setVideoCustomRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(14, 'day'), dayjs()])
  const [liveSort, setLiveSort] = useState<ContentSort>({ sortBy: 'gmv', sortOrder: 'desc' })
  const eligibleShops = useMemo(
    () => (shops.data ?? []).filter((shop) => shopIsInDataRollout(shop, rollout)),
    [rollout, shops.data],
  )
  const selectedShopId = eligibleShops.some((shop) => shop.id === shopId) ? shopId : eligibleShops[0]?.id
  const timezone = eligibleShops.find((shop) => shop.id === selectedShopId)?.timezone
  const videoMaxDate = useShopLocalToday(timezone ?? undefined)
  const videoRangeResult = useMemo(() => {
    if (!timezone) return { error: '店铺未配置时区，无法计算视频时间范围。' }
    try {
      return {
        range: resolveVideoRange({
          preset: videoRangePreset,
          timezone,
          customRange: videoCustomRange,
        }),
      }
    } catch (error) {
      return { error: error instanceof Error ? error.message : '视频时间范围无效。' }
    }
  }, [timezone, videoRangePreset, videoCustomRange])
  const query = useMemo(
    () => ({
      shopId: selectedShopId ?? '',
      from: range[0].startOf('day').toISOString(),
      to: range[1].add(1, 'day').startOf('day').toISOString(),
      currency,
      granularity,
    }),
    [selectedShopId, range, currency, granularity],
  )
  const periodDays = range[1].startOf('day').diff(range[0].startOf('day'), 'day') + 1
  const previousQuery = useMemo(
    () => ({
      ...query,
      from: range[0].subtract(periodDays, 'day').startOf('day').toISOString(),
      to: range[0].startOf('day').toISOString(),
    }),
    [periodDays, query, range],
  )
  const enabled = Boolean(selectedShopId)
  const overview = useOverviewQuery(query, enabled)
  const trends = useTrendsQuery(query, enabled)
  const previousTrends = useTrendsQuery(previousQuery, enabled)
  const videoQuery =
    selectedShopId && videoRangeResult.range
      ? {
          shopId: selectedShopId,
          from: videoRangeResult.range.from,
          to: videoRangeResult.range.to,
          currency: videoRangeResult.range.currency,
          accountType: videoRangeResult.range.accountType,
        }
      : undefined
  const videos = useVideosQuery(videoQuery, videoSort)
  const lives = useLivesQuery(selectedShopId, liveSort)
  const sync = useSyncStatusQuery(selectedShopId)
  const syncHealth = useSyncHealthQuery(selectedShopId)
  const resync = useResyncMutation()
  const resyncError = resyncErrorMessage(resync.error)
  const videoPendingText = videoRangeResult.range
    ? `正在获取 ${videoRangeResult.range.displayFrom} 至 ${videoRangeResult.range.displayTo} 的视频数据……`
    : undefined
  const latestVideoDate = videos.data?.range.latestAvailableDate
  const videoUnavailableText =
    videoRangePreset === 'today' && latestVideoDate
      ? `今日暂无数据 · TikTok 数据目前更新至 ${latestVideoDate}`
      : undefined
  const refetch = () =>
    [overview, trends, previousTrends, videos, lives, sync, syncHealth].forEach((item) => void item.refetch())

  if (shops.isLoading) return <PageLoading fullscreen />
  if (shops.isError)
    return (
      <PageError
        title="无法加载店铺"
        description="店铺选择器需要 shops:view 权限。"
        onRetry={() => void shops.refetch()}
      />
    )
  if (!shops.data?.length) return <Empty description="当前租户没有可用店铺" />
  if (!eligibleShops.length) {
    return (
      <DataUnavailablePage
        title="当前店铺尚未进入灰度"
        description="数据模块当前仅向本阶段允许的店铺开放，可随时切回旧占位页。"
      />
    )
  }
  return (
    <Space className="data-page" orientation="vertical" size="large">
      <div className="data-page-header">
        <div>
          <Typography.Title level={2}>数据</Typography.Title>
          <Typography.Text type="secondary">
            时间按店铺时区展示：{timezone ?? '未配置'}；金额按快照 currency 展示。
          </Typography.Text>
        </div>
      </div>
      <Card className="data-filter-card" size="small">
        <div className="data-filter-bar">
          <label className="data-filter-field">
            <span>店铺</span>
            <Select
              aria-label="店铺"
              value={selectedShopId}
              onChange={setShopId}
              options={eligibleShops.map((shop) => ({ value: shop.id, label: shop.shopName }))}
              style={{ width: 190 }}
            />
          </label>
          <label className="data-filter-field">
            <span>日期</span>
            <RangePicker
              aria-label="日期范围"
              value={range}
              onChange={(value) => value?.[0] && value[1] && setRange([value[0], value[1]])}
            />
          </label>
          <label className="data-filter-field">
            <span>粒度</span>
            <Select
              aria-label="粒度"
              value={granularity}
              onChange={setGranularity}
              options={[
                { value: 'day', label: '按日' },
                { value: 'hour', label: '按小时' },
              ]}
              style={{ width: 92 }}
            />
          </label>
          <label className="data-filter-field">
            <span>币种</span>
            <Select
              aria-label="币种"
              value={currency}
              onChange={setCurrency}
              options={[{ value: 'USD', label: 'USD' }]}
              style={{ width: 82 }}
            />
          </label>
          <Space className="data-filter-actions">
            <Button icon={<ReloadOutlined />} onClick={refetch}>
              刷新本地数据
            </Button>
            {hasPermissions([modulePermissionCodes.syncTrigger]) && (
              <Button
                type="primary"
                loading={resync.isPending}
                onClick={() => selectedShopId && resync.mutate({ shopId: selectedShopId }, { onSuccess: refetch })}
              >
                重新同步
              </Button>
            )}
          </Space>
        </div>
      </Card>
      {isDataMock && (
        <Alert
          description="当前页面展示的是仅供界面开发的模拟数据，不代表店铺实际数据。"
          title="Mock 模式已启用"
          showIcon
          type="info"
        />
      )}
      {resync.isError && (
        <Alert description={resyncError.description} title={resyncError.title} showIcon type="error" />
      )}
      <section>
        <Typography.Title level={4}>核心指标</Typography.Title>
        <MetricCards query={overview} />
      </section>
      <TrendCard query={trends} previousQuery={previousTrends} timezone={timezone} periodDays={periodDays} />
      <div className="data-table-grid">
        <Card
          title="视频数据"
          extra={
            <VideoRangeControls
              preset={videoRangePreset}
              customRange={videoCustomRange}
              maxDate={videoMaxDate}
              canRefresh={hasPermissions([modulePermissionCodes.syncTrigger])}
              refreshing={resync.isPending}
              onPresetChange={setVideoRangePreset}
              onCustomRangeChange={setVideoCustomRange}
              onRefresh={() =>
                videoQuery &&
                resync.mutate(
                  {
                    shopId: videoQuery.shopId,
                    resourceTypes: ['video'],
                    windowStart: videoQuery.from,
                    windowEnd: videoQuery.to,
                    currency: videoQuery.currency,
                    accountType: videoQuery.accountType,
                  },
                  { onSuccess: () => void videos.refetch() },
                )
              }
            />
          }
        >
          {videoRangeResult.range && (
            <VideoRangeSummary
              displayFrom={videoRangeResult.range.displayFrom}
              displayTo={videoRangeResult.range.displayTo}
              asOf={videos.data?.freshness.asOf}
              timezone={timezone}
            />
          )}
          {videoRangeResult.error ? (
            <Alert message={videoRangeResult.error} showIcon type="warning" />
          ) : (
            <ContentRankingTable
              kind="video"
              query={videos}
              timezone={timezone}
              sort={videoSort}
              onSortChange={setVideoSort}
              pendingText={videoPendingText}
              unavailableText={videoUnavailableText}
            />
          )}
        </Card>
        <Card title="直播数据">
          <ContentRankingTable
            kind="live"
            query={lives}
            timezone={timezone}
            sort={liveSort}
            onSortChange={setLiveSort}
          />
        </Card>
      </div>
      <DataStatusCard videos={videos} lives={lives} sync={sync} health={syncHealth} timezone={timezone} />
    </Space>
  )
}
