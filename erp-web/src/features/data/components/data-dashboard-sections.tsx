import { Alert, Card, Empty, Spin, Statistic, Table, Typography } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import type { AnalyticsContent, AnalyticsSnapshot, ContentSort, ContentSortBy, DataEnvelope } from '../types/data.types'
import { renderPromotedProducts, renderVideoTitle } from './content-media-cells'
import { liveColumns } from './live-ranking-columns'
import { PlatformContentId } from './platform-content-id'

type DataQuery<T> = {
  data?: DataEnvelope<T>
  error?: unknown
  isError?: boolean
  isLoading: boolean
}

const metricDefinitions = [
  { key: 'gmv', label: '成交金额', aliases: ['gmv', 'gmvAmount'] },
  { key: 'orders', label: '成交订单', aliases: ['orders', 'orderCount'] },
  { key: 'videoProductClicks', label: '视频商品点击', aliases: ['videoProductClicks'] },
  { key: 'liveCustomers', label: '直播成交客户', aliases: ['liveCustomers'] },
  {
    key: 'latestLiveClickToOrderRate',
    label: '最近一日直播点击成交率',
    aliases: ['latestLiveClickToOrderRate'],
    rate: true,
  },
] as const

const timeFormatOptions: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
}

const isMoney = (value: unknown): value is { amountMinor: number; currency: string } =>
  Boolean(value && typeof value === 'object' && typeof (value as { amountMinor?: unknown }).amountMinor === 'number')

const numberValue = (value: unknown) => {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : null
}

const formatMetricValue = (value: unknown, rate = false) => {
  if (isMoney(value))
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: value.currency }).format(
      value.amountMinor / 100,
    )
  const numeric = numberValue(value)
  if (numeric === null) return '--'
  return new Intl.NumberFormat('zh-CN', rate ? { style: 'percent', maximumFractionDigits: 2 } : {}).format(numeric)
}

const formatDataTime = (value?: string | null, timezone?: string | null) => {
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

const field = (row: AnalyticsContent, ...keys: string[]) =>
  keys.map((key) => row.fields[key]).find((value) => value !== undefined && value !== null)

const formatText = (value: unknown) => (typeof value === 'string' && value.trim() ? value : '--')

const formatCount = (value: unknown) => {
  const numeric = numberValue(value)
  return numeric === null ? '--' : new Intl.NumberFormat('zh-CN').format(numeric)
}

const formatRate = (value: unknown) => {
  const numeric = numberValue(value)
  return numeric === null
    ? '--'
    : new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(numeric)
}

const formatDuration = (value: unknown) => {
  const numeric = numberValue(value)
  if (numeric === null || numeric < 0) return '--'
  const totalSeconds = Math.floor(numeric)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds]
    .map((part) => String(part).padStart(2, '0'))
    .join(':')
    .replace(/^00:/, '')
}

const authorTypeLabels: Record<string, string> = {
  OFFICIAL: '官方账号',
  OFFICIAL_ACCOUNTS: '官方账号',
  CHANNEL: '渠道账号',
  MARKETING_ACCOUNTS: '营销账号',
  AFFILIATE: '联盟达人',
  AFFILIATE_ACCOUNTS: '联盟达人',
}

const formatAuthorType = (value: unknown) => {
  const text = formatText(value)
  return text === '--' ? text : (authorTypeLabels[text] ?? text)
}

const accountTypeFilters = [
  { text: '官方账号', value: 'official' },
  { text: '渠道账号', value: 'channel' },
  { text: '营销账号', value: 'marketing' },
  { text: '联盟达人', value: 'affiliate' },
]

const accountTypeFilterValue = (value: unknown) => {
  const text = typeof value === 'string' ? value.toUpperCase() : ''
  if (text.startsWith('OFFICIAL')) return 'official'
  if (text.startsWith('CHANNEL')) return 'channel'
  if (text.startsWith('MARKETING')) return 'marketing'
  if (text.startsWith('AFFILIATE')) return 'affiliate'
  return text.toLowerCase()
}

const renderHashTags = (value: unknown) => {
  if (!Array.isArray(value) || !value.length) return '--'
  const tags = value.filter((tag): tag is string => typeof tag === 'string' && Boolean(tag.trim()))
  return tags.length ? (
    <div className="data-video-tags">
      {tags.map((tag) => (
        <span key={tag}>#{tag}</span>
      ))}
    </div>
  ) : (
    '--'
  )
}

const formatMoneyFields = (row: AnalyticsContent, amountKey: string, currencyKey: string) => {
  const amount = numberValue(row.fields[amountKey])
  const currency = row.fields[currencyKey]
  if (amount === null || typeof currency !== 'string' || !currency) return '--'
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

const queryNote = (query: DataQuery<unknown[]>, emptyText: string) => {
  if (query.isLoading) return '正在加载数据…'
  if (query.isError) return '数据加载失败，请稍后刷新。'
  if (query.data?.freshness.isStale) return '暂无本地快照，重新同步后将在此展示。'
  return emptyText
}

export function MetricCards({ query }: { query: DataQuery<AnalyticsSnapshot[]> }) {
  const metrics = query.data?.data.at(-1)?.metrics ?? {}
  return (
    <div>
      <div className="data-metric-grid">
        {metricDefinitions.map((metric) => {
          const value = metric.aliases.map((alias) => metrics[alias]).find((item) => item !== undefined)
          return (
            <Card key={metric.key} size="small">
              <Statistic title={metric.label} value={formatMetricValue(value, 'rate' in metric && metric.rate)} />
            </Card>
          )
        })}
      </div>
      {(!query.data?.data.length || query.isError) && (
        <Typography.Text className="data-section-note" type="secondary">
          {queryNote(query, '当前时间范围暂无核心指标。')}
        </Typography.Text>
      )}
    </div>
  )
}

export { TrendCard } from './trend-card'

const rankColumn: ColumnsType<AnalyticsContent>[number] = {
  title: '排名',
  fixed: 'left',
  width: 56,
  render: (_value, _row, index) => index + 1,
}

const tableSortOrder = (sort: ContentSort, sortBy: ContentSortBy) =>
  sort.sortBy === sortBy ? (sort.sortOrder === 'desc' ? 'descend' : 'ascend') : null

const videoColumns = (sort: ContentSort, timezone?: string | null): ColumnsType<AnalyticsContent> => [
  rankColumn,
  { title: '创作者昵称', fixed: 'left', width: 132, render: (_, row) => formatText(field(row, 'creatorNickname')) },
  { title: '创作者用户名', fixed: 'left', width: 140, render: (_, row) => formatText(field(row, 'creatorUsername')) },
  { title: '视频', width: 210, render: (_, row) => renderVideoTitle(field(row, 'title')) },
  { title: '视频 ID', width: 190, render: (_, row) => <PlatformContentId value={row.platformExternalId} /> },
  { title: '播放量（所选时间）', width: 144, align: 'right', render: (_, row) => formatCount(field(row, 'views')) },
  { title: '商品点击率', width: 108, align: 'right', render: (_, row) => formatRate(field(row, 'clickThroughRate')) },
  { title: '日均客户数', width: 104, align: 'right', render: (_, row) => formatCount(field(row, 'averageCustomers')) },
  {
    title: 'GMV',
    key: 'gmv',
    width: 120,
    align: 'right',
    sorter: true,
    sortOrder: tableSortOrder(sort, 'gmv'),
    sortDirections: ['descend', 'ascend', 'descend'],
    render: (_, row) => formatMoneyFields(row, 'gmvAmount', 'gmvCurrency'),
  },
  {
    title: 'GPM',
    key: 'gpm',
    width: 120,
    align: 'right',
    sorter: true,
    sortOrder: tableSortOrder(sort, 'gpm'),
    sortDirections: ['descend', 'ascend', 'descend'],
    render: (_, row) => formatMoneyFields(row, 'gpmAmount', 'gpmCurrency'),
  },
  { title: '时长', width: 76, render: (_, row) => formatDuration(field(row, 'durationSeconds')) },
  { title: '2秒停留率', width: 104, align: 'right', render: (_, row) => formatRate(field(row, 'retention2sRate')) },
  { title: '6秒停留率', width: 104, align: 'right', render: (_, row) => formatRate(field(row, 'retention6sRate')) },
  { title: '25%停留率', width: 108, align: 'right', render: (_, row) => formatRate(field(row, 'retention25Rate')) },
  { title: '50%停留率', width: 108, align: 'right', render: (_, row) => formatRate(field(row, 'retention50Rate')) },
  { title: '75%停留率', width: 108, align: 'right', render: (_, row) => formatRate(field(row, 'retention75Rate')) },
  {
    title: '100%停留率',
    width: 116,
    align: 'right',
    render: (_, row) => formatRate(field(row, 'retention100Rate', 'completionRate')),
  },
  { title: '标签', width: 150, render: (_, row) => renderHashTags(field(row, 'hashTags')) },
  {
    title: '发布时间',
    key: 'publishedAt',
    width: 190,
    sorter: true,
    sortOrder: tableSortOrder(sort, 'publishedAt'),
    sortDirections: ['descend', 'ascend', 'descend'],
    render: (_, row) => formatDataTime(formatText(field(row, 'videoPostTime')), timezone),
  },
  {
    title: '账号类型',
    width: 112,
    filters: accountTypeFilters,
    filterMultiple: true,
    onFilter: (value, row) => accountTypeFilterValue(field(row, 'creatorAuthorType')) === value,
    render: (_, row) => formatAuthorType(field(row, 'creatorAuthorType')),
  },
  { title: '推广商品', width: 180, render: (_, row) => renderPromotedProducts(field(row, 'promotedProducts')) },
]

export function ContentRankingTable({
  kind,
  query,
  timezone,
  sort,
  onSortChange,
  pendingText,
  unavailableText,
}: {
  kind: 'video' | 'live'
  query: DataQuery<AnalyticsContent[]>
  timezone?: string | null
  sort: ContentSort
  onSortChange: (sort: ContentSort) => void
  pendingText?: string
  unavailableText?: string
}) {
  if (query.isError) {
    return (
      <Alert
        title={kind === 'video' ? '视频数据加载失败' : '直播数据加载失败'}
        description="当前请求失败，未显示其他时间范围或 Mock 数据，请稍后重试。"
        showIcon
        type="error"
      />
    )
  }
  const rows = query.data?.data ?? []
  const handleChange: NonNullable<TableProps<AnalyticsContent>['onChange']> = (_pagination, _filters, sorter) => {
    const selected = Array.isArray(sorter) ? sorter[0] : sorter
    if (!selected.columnKey || !selected.order) return
    onSortChange({
      sortBy: selected.columnKey as ContentSortBy,
      sortOrder: selected.order === 'ascend' ? 'asc' : 'desc',
    })
  }
  if (kind === 'video' && pendingText && (query.isLoading || query.data?.freshness.isStale)) {
    return (
      <div className="data-video-syncing" role="status">
        <Spin size="small" />
        <Typography.Text>{pendingText}</Typography.Text>
      </div>
    )
  }
  if (
    kind === 'video' &&
    unavailableText &&
    rows.length === 0 &&
    !query.isLoading &&
    query.data?.freshness.isStale === false
  ) {
    return <Empty description={unavailableText} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  return (
    <Table
      className={`data-ranking-table data-${kind}-ranking-table`}
      columns={kind === 'video' ? videoColumns(sort, timezone) : liveColumns(sort, timezone)}
      dataSource={rows}
      rowKey="platformExternalId"
      loading={query.isLoading}
      locale={{ emptyText: queryNote(query, kind === 'video' ? '暂无视频经营数据' : '暂无直播经营数据') }}
      pagination={false}
      onChange={handleChange}
      showSorterTooltip={{ target: 'sorter-icon' }}
      scroll={{ x: kind === 'video' ? 2640 : 2330, y: 520 }}
      size="small"
    />
  )
}
