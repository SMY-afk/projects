import { Table, Tooltip } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import type {
  AffiliateLiveAccountMetric,
  AffiliateLiveSortBy,
  AffiliateLiveSortOrder,
} from '../types/affiliate-live-account.types'

const field = (row: AffiliateLiveAccountMetric, ...keys: string[]) =>
  keys.map((key) => row.fields[key]).find((value) => value !== undefined && value !== null)

const numeric = (value: unknown) => {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN
  return Number.isFinite(parsed) ? parsed : null
}

const count = (value: unknown) => {
  const parsed = numeric(value)
  return parsed === null ? '—' : new Intl.NumberFormat('zh-CN').format(parsed)
}

const money = (row: AffiliateLiveAccountMetric, amountKey: string, currencyKey: string) => {
  const amount = numeric(row.fields[amountKey])
  const currency = row.fields[currencyKey]
  if (amount === null || typeof currency !== 'string' || !currency) return '—'
  try {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency }).format(amount)
  } catch {
    return `${amount} ${currency}`
  }
}

const rate = (value: unknown) => {
  const text = typeof value === 'string' ? value.trim() : value
  const parsed = typeof text === 'string' && text.endsWith('%') ? numeric(text.slice(0, -1)) : numeric(text)
  if (parsed === null) return '—'
  const normalized = typeof text === 'string' && text.endsWith('%') ? parsed / 100 : parsed
  return new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(normalized)
}

const time = (value: unknown, timezone?: string | null) => {
  if ((typeof value !== 'string' && typeof value !== 'number') || !timezone) return '—'
  const seconds = typeof value === 'number' ? value : /^\d+$/.test(value) ? Number(value) : null
  const date = seconds === null ? new Date(value) : new Date(seconds * 1000)
  if (Number.isNaN(date.getTime())) return '—'
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      dateStyle: 'short',
      timeStyle: 'short',
      timeZone: timezone,
    }).format(date)
  } catch {
    return '—'
  }
}

const sortOrder = (active: AffiliateLiveSortBy, order: AffiliateLiveSortOrder, key: AffiliateLiveSortBy) =>
  active === key ? (order === 'desc' ? 'descend' : 'ascend') : null

export function AffiliateLiveAccountTable({
  rows,
  loading,
  timezone,
  sortBy,
  sortOrder: order,
  page,
  pageSize,
  total,
  onPageChange,
  onSortChange,
}: {
  rows: AffiliateLiveAccountMetric[]
  loading: boolean
  timezone?: string | null
  sortBy: AffiliateLiveSortBy
  sortOrder: AffiliateLiveSortOrder
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number, pageSize: number) => void
  onSortChange: (sortBy: AffiliateLiveSortBy, sortOrder: AffiliateLiveSortOrder) => void
}) {
  const columns: ColumnsType<AffiliateLiveAccountMetric> = [
    { title: '排名', width: 64, render: (_value, _row, index) => (page - 1) * pageSize + index + 1 },
    { title: '联盟账号', width: 140, render: (_, row) => field(row, 'username') ?? '—' },
    {
      title: '直播场次',
      width: 220,
      render: (_, row) => {
        const title = field(row, 'title')
        return typeof title === 'string' && title ? <Tooltip title={title}>{title}</Tooltip> : '—'
      },
    },
    { title: '直播 ID', width: 190, dataIndex: 'platformExternalId' },
    {
      title: 'GMV',
      key: 'gmv',
      width: 120,
      align: 'right',
      sorter: true,
      sortOrder: sortOrder(sortBy, order, 'gmv'),
      render: (_, row) => money(row, 'gmvAmount', 'gmvCurrency'),
    },
    { title: '支付订单', width: 104, align: 'right', render: (_, row) => count(field(row, 'skuOrders')) },
    { title: '销量', width: 88, align: 'right', render: (_, row) => count(field(row, 'itemsSold')) },
    { title: '下单客户', width: 104, align: 'right', render: (_, row) => count(field(row, 'customers')) },
    { title: '点击成交率', width: 112, align: 'right', render: (_, row) => rate(field(row, 'clickToOrderRate')) },
    { title: '观看次数', width: 104, align: 'right', render: (_, row) => count(field(row, 'views')) },
    { title: '直播点击率', width: 112, align: 'right', render: (_, row) => rate(field(row, 'clickThroughRate')) },
    {
      title: '开播时间',
      key: 'startedAt',
      width: 170,
      sorter: true,
      sortOrder: sortOrder(sortBy, order, 'startedAt'),
      render: (_, row) => time(field(row, 'startTime'), timezone),
    },
    { title: '结束时间', width: 170, render: (_, row) => time(field(row, 'endTime'), timezone) },
  ]
  const handleChange: NonNullable<TableProps<AffiliateLiveAccountMetric>['onChange']> = (
    pagination,
    _filters,
    sorter,
  ) => {
    const nextPage = pagination.current ?? page
    const nextPageSize = pagination.pageSize ?? pageSize
    if (nextPage !== page || nextPageSize !== pageSize) {
      onPageChange(nextPage, nextPageSize)
    }
    const selected = Array.isArray(sorter) ? sorter[0] : sorter
    if (!selected.columnKey || !selected.order) return
    onSortChange(selected.columnKey as AffiliateLiveSortBy, selected.order === 'ascend' ? 'asc' : 'desc')
  }

  return (
    <Table
      columns={columns}
      dataSource={rows}
      loading={loading}
      locale={{ emptyText: '暂无联盟账号直播数据' }}
      pagination={{
        current: page,
        pageSize,
        total,
        pageSizeOptions: [20, 50, 100],
        showSizeChanger: true,
        showTotal: (count) => `共 ${count} 条`,
      }}
      rowKey="platformExternalId"
      scroll={{ x: 1720, y: 520 }}
      size="small"
      onChange={handleChange}
    />
  )
}
