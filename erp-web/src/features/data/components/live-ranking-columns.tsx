import { Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { AnalyticsContent, ContentSort } from '../types/data.types'
import { PlatformContentId } from './platform-content-id'

const field = (row: AnalyticsContent, ...keys: string[]) =>
  keys.map((key) => row.fields[key]).find((value) => value !== undefined && value !== null)

const numeric = (value: unknown) => {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : null
}

const formatCount = (value: unknown) => {
  const parsed = numeric(value)
  return parsed === null ? '--' : new Intl.NumberFormat('zh-CN').format(parsed)
}

const formatRate = (value: unknown) => {
  const normalized = typeof value === 'string' ? value.trim() : value
  const parsed =
    typeof normalized === 'string' && normalized.endsWith('%') ? numeric(normalized.slice(0, -1)) : numeric(normalized)
  if (parsed === null) return '--'
  const rate = typeof normalized === 'string' && normalized.endsWith('%') ? parsed / 100 : parsed
  return new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(rate)
}

const formatMoney = (row: AnalyticsContent, amountKey: string, currencyKey: string) => {
  const amount = numeric(row.fields[amountKey])
  const currency = row.fields[currencyKey]
  if (amount === null || typeof currency !== 'string' || !currency) return '--'
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

const formatTime = (value: unknown, timezone?: string | null) => {
  if ((typeof value !== 'string' && typeof value !== 'number') || !timezone) return '--'
  const seconds = typeof value === 'number' ? value : /^\d+$/.test(value) ? Number(value) : null
  const date = seconds === null ? new Date(value) : new Date(seconds * 1000)
  if (Number.isNaN(date.getTime())) return '--'
  try {
    return `${new Intl.DateTimeFormat('sv-SE', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
      timeZone: timezone,
    }).format(date)} ${timezone}`
  } catch {
    return '--'
  }
}

const accountLabels: Record<string, string> = {
  OFFICIAL_ACCOUNTS: '官方账号',
  MARKETING_ACCOUNTS: '营销账号',
  AFFILIATE_ACCOUNTS: '联盟达人',
}

const renderAccountType = (row: AnalyticsContent) => {
  const value = field(row, 'accountType')
  return typeof value === 'string' ? (accountLabels[value] ?? value) : '--'
}

const renderTitle = (row: AnalyticsContent) => {
  const value = field(row, 'title')
  if (typeof value !== 'string' || !value.trim()) return '--'
  return (
    <Tooltip title={value}>
      <span className="data-live-title">{value}</span>
    </Tooltip>
  )
}

const renderInteraction = (row: AnalyticsContent, keys: string[], rate = false) => {
  if (field(row, 'accountType') === 'AFFILIATE_ACCOUNTS') {
    return (
      <Tooltip title="平台仅向官方号或营销号提供该互动指标">
        <Typography.Text type="secondary">不适用</Typography.Text>
      </Tooltip>
    )
  }
  const value = field(row, ...keys)
  if (value === undefined || value === null) {
    return (
      <Tooltip title="等待官方号或营销号直播明细同步">
        <Typography.Text type="secondary">待同步</Typography.Text>
      </Tooltip>
    )
  }
  return rate ? formatRate(value) : formatCount(value)
}

const sortOrder = (sort: ContentSort, sortBy: 'gmv' | 'startedAt') =>
  sort.sortBy === sortBy ? (sort.sortOrder === 'desc' ? 'descend' : 'ascend') : null

export const liveColumns = (sort: ContentSort, timezone?: string | null): ColumnsType<AnalyticsContent> => [
  { title: '排名', fixed: 'left', width: 56, render: (_value, _row, index) => index + 1 },
  { title: '主播账号', fixed: 'left', width: 140, render: (_, row) => field(row, 'username') ?? '--' },
  { title: '直播场次', fixed: 'left', width: 180, render: (_, row) => renderTitle(row) },
  { title: '直播 ID', width: 190, render: (_, row) => <PlatformContentId value={row.platformExternalId} /> },
  { title: '账号类型', width: 110, render: (_, row) => renderAccountType(row) },
  {
    title: '销售数据',
    children: [
      {
        title: 'GMV',
        key: 'gmv',
        width: 120,
        align: 'right',
        sorter: true,
        sortOrder: sortOrder(sort, 'gmv'),
        sortDirections: ['descend', 'ascend', 'descend'],
        render: (_, row) => formatMoney(row, 'gmvAmount', 'gmvCurrency'),
      },
      {
        title: '创建订单',
        width: 104,
        align: 'right',
        render: (_, row) => formatCount(field(row, 'createdSkuOrders')),
      },
      { title: '支付订单', width: 104, align: 'right', render: (_, row) => formatCount(field(row, 'skuOrders')) },
      { title: '销量', width: 88, align: 'right', render: (_, row) => formatCount(field(row, 'itemsSold')) },
      { title: '下单客户', width: 104, align: 'right', render: (_, row) => formatCount(field(row, 'customers')) },
      {
        title: '客单价',
        width: 120,
        align: 'right',
        render: (_, row) => formatMoney(row, 'averagePriceAmount', 'averagePriceCurrency'),
      },
      { title: '添加商品', width: 96, align: 'right', render: (_, row) => formatCount(field(row, 'productsAdded')) },
      {
        title: '售出商品种类',
        width: 120,
        align: 'right',
        render: (_, row) => formatCount(field(row, 'differentProductsSold')),
      },
      {
        title: '点击成交率',
        width: 112,
        align: 'right',
        render: (_, row) => formatRate(field(row, 'clickToOrderRate')),
      },
    ],
  },
  {
    title: '互动数据（官方/营销号）',
    children: [
      {
        title: '观看次数',
        width: 104,
        align: 'right',
        render: (_, row) => renderInteraction(row, ['views', 'watchPv']),
      },
      {
        title: '点赞数',
        width: 88,
        align: 'right',
        render: (_, row) => renderInteraction(row, ['likes', 'likeCount']),
      },
      {
        title: '评论数',
        width: 88,
        align: 'right',
        render: (_, row) => renderInteraction(row, ['comments', 'commentCount']),
      },
      {
        title: '商品点击率',
        width: 112,
        align: 'right',
        render: (_, row) => renderInteraction(row, ['clickThroughRate'], true),
      },
    ],
  },
  {
    title: '开播时间',
    key: 'startedAt',
    width: 190,
    sorter: true,
    sortOrder: sortOrder(sort, 'startedAt'),
    sortDirections: ['descend', 'ascend', 'descend'],
    render: (_, row) => formatTime(field(row, 'startTime'), timezone),
  },
  { title: '结束时间', width: 190, render: (_, row) => formatTime(field(row, 'endTime'), timezone) },
]
