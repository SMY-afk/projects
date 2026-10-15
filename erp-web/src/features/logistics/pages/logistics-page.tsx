import { Button, Card, DatePicker, Select, Space, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import { getLogisticsStatusPresentation, LOGISTICS_STATUS_STEPS } from '../components/logistics-status'
import { LogisticsStatusSteps } from '../components/logistics-status-steps'
import { useLogisticsShopOptionsQuery, useLogisticsTaskListQuery } from '../queries/logistics.queries'
import type {
  LogisticsPriority,
  LogisticsSourceType,
  LogisticsTask,
  LogisticsTaskListParams,
  LogisticsTaskStatus,
} from '../types/logistics.types'
import './logistics-page.css'

const statusOptions = [
  ...LOGISTICS_STATUS_STEPS.map((item) => ({ label: item.title, value: item.key })),
  { label: '已取消', value: 'cancelled' },
]
const sourceOptions = [
  { label: '销售订单', value: 'sales_order' },
  { label: '退货单', value: 'return' },
  { label: '换货单', value: 'exchange' },
]

const sourceLabels: Record<LogisticsSourceType, string> = {
  sales_order: '销售订单',
  return: '退货单',
  exchange: '换货单',
}
const priorityOptions = [
  { label: '低', value: 'low' },
  { label: '普通', value: 'normal' },
  { label: '高', value: 'high' },
  { label: '紧急', value: 'urgent' },
]
const priorityPresentation = {
  low: { label: '低', color: 'default' },
  normal: { label: '普通', color: 'blue' },
  high: { label: '高', color: 'orange' },
  urgent: { label: '紧急', color: 'red' },
} as const

export default function LogisticsPage() {
  const navigate = useNavigate()
  const [params, setParams] = useState<LogisticsTaskListParams>({ page: 1, pageSize: 20 })
  const query = useLogisticsTaskListQuery(params)
  const shopsQuery = useLogisticsShopOptionsQuery()
  const shopNames = useMemo(
    () => new Map((shopsQuery.data ?? []).map((shop) => [shop.id, shop.shopName])),
    [shopsQuery.data],
  )
  const setFilter = (change: Partial<LogisticsTaskListParams>) =>
    setParams((current) => ({ ...current, ...change, page: 1 }))

  const columns = [
    {
      title: '任务编号',
      dataIndex: 'taskNumber',
      render: (_: string, task: LogisticsTask) => (
        <Button type="link" onClick={() => void navigate(`/logistics/tasks/${task.id}`)}>
          {task.taskNumber}
        </Button>
      ),
    },
    { title: '店铺', render: (_: unknown, task: LogisticsTask) => shopNames.get(task.shopId ?? '') ?? '-' },
    { title: '来源单号', dataIndex: 'sourceNumber' },
    {
      title: '来源',
      dataIndex: 'sourceType',
      render: (value: LogisticsSourceType) => sourceLabels[value],
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (value: LogisticsTaskStatus) => getLogisticsStatusPresentation(value).label,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      render: (value: LogisticsPriority) => (
        <Tag color={priorityPresentation[value].color}>{priorityPresentation[value].label}</Tag>
      ),
    },
    {
      title: '商品数量',
      render: (_: unknown, task: LogisticsTask) => task.items.reduce((total, item) => total + item.plannedQuantity, 0),
    },
    { title: '创建时间', dataIndex: 'createdAt', render: (value: string) => new Date(value).toLocaleString() },
  ]

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <div>
        <Typography.Title level={2}>物流任务中心</Typography.Title>
        <Typography.Text type="secondary">按店铺和业务状态管理物流任务；本期不提供仓库筛选。</Typography.Text>
      </div>
      <LogisticsSectionNav />
      <Card title="任务状态流程">
        <LogisticsStatusSteps status="pending_review" />
      </Card>
      <Card>
        <Space className="logistics-task-filters" wrap>
          <Select
            allowClear
            loading={shopsQuery.isLoading}
            onChange={(shopId) => setFilter({ shopId })}
            options={(shopsQuery.data ?? []).map((shop) => ({ label: shop.shopName, value: shop.id }))}
            placeholder="全部店铺"
            value={params.shopId}
          />
          <Select
            allowClear
            onChange={(sourceType) => setFilter({ sourceType })}
            options={sourceOptions}
            placeholder="全部来源"
            value={params.sourceType}
          />
          <Select
            allowClear
            onChange={(status) => setFilter({ status })}
            options={statusOptions}
            placeholder="全部状态"
            value={params.status}
          />
          <Select
            allowClear
            onChange={(priority) => setFilter({ priority })}
            options={priorityOptions}
            placeholder="全部优先级"
            value={params.priority}
          />
          <DatePicker.RangePicker
            showTime
            onChange={(range) =>
              setFilter({
                createdFrom: range?.[0]?.toISOString(),
                createdTo: range?.[1]?.toISOString(),
              })
            }
          />
          <Button onClick={() => setParams({ page: 1, pageSize: 20 })}>重置</Button>
        </Space>
        <Table<LogisticsTask>
          columns={columns}
          dataSource={query.data?.items ?? []}
          loading={query.isLoading}
          rowKey="id"
          pagination={{
            current: params.page,
            pageSize: params.pageSize,
            total: query.data?.total ?? 0,
            onChange: (page) => setParams((current) => ({ ...current, page })),
          }}
        />
      </Card>
    </Space>
  )
}
