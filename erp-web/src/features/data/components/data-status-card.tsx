import { Alert, Card, Empty, Spin, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { AnalyticsContent, AnalyticsSyncRun, DataEnvelope, SyncHealth } from '../types/data.types'
import { DataQueryState } from './data-query-state'
import { syncErrorMessage } from './sync-error-message'

type DataQuery<T> = {
  data?: DataEnvelope<T>
  error?: unknown
  isError?: boolean
  isLoading: boolean
}

type StatusRow = AnalyticsContent & { resourceType: '视频' | '直播' }

const timeFormatOptions: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}

const formatTime = (value?: string | null, timezone?: string | null) => {
  if (!value) return '--'
  if (!timezone) return '店铺时区未配置'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  try {
    return `${new Intl.DateTimeFormat('sv-SE', { ...timeFormatOptions, timeZone: timezone }).format(date)} ${timezone}`
  } catch {
    return '店铺时区无效'
  }
}

const formatText = (value: unknown) => (typeof value === 'string' && value.trim() ? value : '--')
const optionalString = (value: unknown) => (typeof value === 'string' ? value : null)

const statusColumns = (timezone?: string | null): ColumnsType<StatusRow> => [
  { title: '类型', dataIndex: 'resourceType', fixed: 'left', width: 64 },
  { title: '平台内容 ID', dataIndex: 'platformExternalId', ellipsis: true, width: 190 },
  { title: '状态', dataIndex: 'status', width: 88, render: (value) => <Tag>{formatText(value)}</Tag> },
  { title: '来源状态', dataIndex: 'sourceStatus', width: 112, render: formatText },
  {
    title: '源数据更新时间',
    dataIndex: 'sourceUpdatedAt',
    width: 220,
    render: (value: unknown) => formatTime(optionalString(value), timezone),
  },
  {
    title: '本地采集时间',
    dataIndex: 'observedAt',
    width: 230,
    render: (value: unknown) => formatTime(optionalString(value), timezone),
  },
]

const syncColumns = (timezone?: string | null): ColumnsType<AnalyticsSyncRun> => [
  { title: '资源', dataIndex: 'resourceType' },
  { title: '状态', dataIndex: 'status', render: (value) => <Tag>{formatText(value)}</Tag> },
  { title: '写入', render: (_, row) => `${row.persistedCount} / ${row.fetchedCount}` },
  {
    title: '新鲜度',
    dataIndex: 'freshAt',
    render: (value: unknown) => formatTime(optionalString(value), timezone),
  },
  { title: '安全摘要', render: (_, row) => syncErrorMessage(row.errorCategory, row.errorSummary) },
]

const healthStatus = {
  healthy: { color: 'success', label: '健康' },
  degraded: { color: 'warning', label: '降级' },
  critical: { color: 'error', label: '严重' },
} as const

const formatDelay = (value: number | null) => {
  if (value === null) return '--'
  if (value < 3600) return `${Math.floor(value / 60)} 分钟`
  if (value < 86400) return `${(value / 3600).toFixed(1)} 小时`
  return `${(value / 86400).toFixed(1)} 天`
}

const healthColumns = (timezone?: string | null): ColumnsType<SyncHealth> => [
  { title: '实体', dataIndex: 'resourceType', render: (value) => (value === 'video' ? '视频' : '直播') },
  {
    title: '健康状态',
    dataIndex: 'status',
    render: (value: SyncHealth['status']) => <Tag color={healthStatus[value].color}>{healthStatus[value].label}</Tag>,
  },
  {
    title: '最后成功同步',
    dataIndex: 'lastSuccessAt',
    render: (value: unknown) => formatTime(optionalString(value), timezone),
  },
  { title: '延迟', dataIndex: 'delaySeconds', render: formatDelay },
  {
    title: '失败率（近7天）',
    dataIndex: 'failureRate',
    render: (value: number | null) => (value === null ? '--' : `${(value * 100).toFixed(1)}%`),
  },
  { title: '429 次数', dataIndex: 'rateLimit429Count' },
  { title: '死信', dataIndex: 'deadLetterCount' },
  { title: '数据缺口', dataIndex: 'dataGapCount' },
]

export function DataStatusCard({
  videos,
  lives,
  sync,
  health,
  timezone,
}: {
  videos: DataQuery<AnalyticsContent[]>
  lives: DataQuery<AnalyticsContent[]>
  sync: DataQuery<AnalyticsSyncRun[]>
  health: { data?: SyncHealth[]; error?: unknown; isError?: boolean; isLoading: boolean }
  timezone?: string | null
}) {
  const statusRows: StatusRow[] = [
    ...(videos.data?.data ?? []).map((row) => ({ ...row, resourceType: '视频' as const })),
    ...(lives.data?.data ?? []).map((row) => ({ ...row, resourceType: '直播' as const })),
  ]
  return (
    <Card
      className="data-status-card"
      title={`数据状态与同步记录 · 更新于 ${formatTime(sync.data?.freshness.asOf, timezone)}`}
    >
      <Tabs
        defaultActiveKey="status"
        items={[
          {
            key: 'health',
            label: '同步健康',
            children: (
              <>
                {health.isLoading ? (
                  <Spin />
                ) : health.isError ? (
                  <Alert type="error" showIcon message="同步健康指标加载失败，请稍后刷新。" />
                ) : health.data?.length ? (
                  <Table
                    columns={healthColumns(timezone)}
                    dataSource={health.data}
                    rowKey={(row) => `${row.shopId}-${row.resourceType}`}
                    pagination={false}
                    scroll={{ x: 960 }}
                    size="small"
                  />
                ) : (
                  <Empty description="暂无同步健康数据" />
                )}
              </>
            ),
          },
          {
            key: 'status',
            label: '数据状态',
            children: (
              <>
                {(videos.isError || lives.isError) && (
                  <Alert type="error" showIcon message="部分内容状态加载失败，请稍后刷新。" />
                )}
                <Table
                  className="data-status-table"
                  columns={statusColumns(timezone)}
                  dataSource={statusRows}
                  rowKey={(row) => `${row.resourceType}-${row.platformExternalId}`}
                  loading={videos.isLoading || lives.isLoading}
                  locale={{ emptyText: '暂无内容数据状态' }}
                  pagination={false}
                  scroll={{ x: 904, y: 360 }}
                  size="small"
                />
              </>
            ),
          },
          {
            key: 'sync',
            label: '同步日志',
            children: (
              <DataQueryState query={{ ...sync, isError: Boolean(sync.isError) }} emptyText="暂无同步运行记录">
                {(data) => (
                  <Table
                    columns={syncColumns(timezone)}
                    dataSource={data}
                    rowKey="runId"
                    pagination={false}
                    size="small"
                  />
                )}
              </DataQueryState>
            ),
          },
        ]}
      />
    </Card>
  )
}
