import { Button, Card, Checkbox, message, Select, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import { LogisticsExceptionDrawer } from '../components/logistics-exception-drawer'
import {
  exceptionSeverityPresentation,
  exceptionStatusPresentation,
  exceptionTypeLabels,
} from '../components/logistics-exception-presentation'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import {
  useLogisticsExceptionActionMutation,
  useLogisticsExceptionListQuery,
  useLogisticsExceptionQuery,
  useSyncPlatformLogisticsMutation,
} from '../queries/logistics.queries'
import type {
  LogisticsException,
  LogisticsExceptionActionRequest,
  LogisticsExceptionListParams,
  LogisticsExceptionSeverity,
  LogisticsExceptionStatus,
  LogisticsExceptionType,
} from '../types/logistics-exception.types'
import './logistics-page.css'

const typeOptions = Object.entries(exceptionTypeLabels).map(([value, label]) => ({ value, label }))
const statusOptions = Object.entries(exceptionStatusPresentation).map(([value, item]) => ({ value, label: item.label }))
const severityOptions = Object.entries(exceptionSeverityPresentation).map(([value, item]) => ({
  value,
  label: item.label,
}))

export default function LogisticsExceptionsPage() {
  const { hasPermissions } = useAuth()
  const [params, setParams] = useState<LogisticsExceptionListParams>({ page: 1, pageSize: 20 })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const listQuery = useLogisticsExceptionListQuery(params)
  const detailQuery = useLogisticsExceptionQuery(selectedId)
  const actionMutation = useLogisticsExceptionActionMutation()
  const platformSyncMutation = useSyncPlatformLogisticsMutation()
  const canOperate = hasPermissions([modulePermissionCodes.logisticsOperate])
  const canManage = hasPermissions([modulePermissionCodes.logisticsManage])
  const setFilter = (change: Partial<LogisticsExceptionListParams>) =>
    setParams((current) => ({ ...current, ...change, page: 1 }))
  const runAction = async (action: string, values: LogisticsExceptionActionRequest) => {
    await actionMutation.mutateAsync({ action, values })
    void message.success('异常处理状态已更新')
  }
  const runDetection = async () => {
    const result = await platformSyncMutation.mutateAsync()
    void message.success(
      `已同步 ${result.packagesSynced} 个真实包裹、${result.trackingEventsSynced} 条轨迹，新识别 ${result.exceptionsDetected} 个异常`,
    )
  }
  const columns = [
    {
      title: '异常编号',
      dataIndex: 'exceptionNumber',
      render: (value: string, record: LogisticsException) => (
        <Button type="link" onClick={() => setSelectedId(record.id)}>
          {value}
        </Button>
      ),
    },
    { title: '物流任务', dataIndex: 'taskNumber' },
    { title: '来源订单', dataIndex: 'sourceNumber' },
    {
      title: '异常类型',
      dataIndex: 'exceptionType',
      render: (value: LogisticsExceptionType) => exceptionTypeLabels[value],
    },
    {
      title: '级别',
      dataIndex: 'severity',
      render: (value: LogisticsExceptionSeverity) => (
        <Tag color={exceptionSeverityPresentation[value].color}>{exceptionSeverityPresentation[value].label}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (value: LogisticsExceptionStatus) => (
        <Tag color={exceptionStatusPresentation[value].color}>{exceptionStatusPresentation[value].label}</Tag>
      ),
    },
    { title: '负责人', render: (_: unknown, record: LogisticsException) => (record.assignedToUserId ? '已认领' : '-') },
    { title: '最近识别', dataIndex: 'lastDetectedAt', render: (value: string) => new Date(value).toLocaleString() },
  ]

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <div className="logistics-title-actions">
        <div>
          <Typography.Title level={2}>物流异常中心</Typography.Title>
          <Typography.Text type="secondary">
            处理未揽收、滞留、地址错误、拒收、丢失、破损及平台状态差异。
          </Typography.Text>
        </div>
        {canManage && (
          <Button loading={platformSyncMutation.isPending} onClick={() => void runDetection()}>
            同步平台物流并识别
          </Button>
        )}
      </div>
      <LogisticsSectionNav />
      <Card>
        <Space className="logistics-task-filters" wrap>
          <Select
            allowClear
            onChange={(type) => setFilter({ type })}
            options={typeOptions}
            placeholder="全部异常类型"
            value={params.type}
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
            onChange={(severity) => setFilter({ severity })}
            options={severityOptions}
            placeholder="全部级别"
            value={params.severity}
          />
          <Checkbox
            checked={params.assignedToMe}
            onChange={(event) => setFilter({ assignedToMe: event.target.checked })}
          >
            只看我认领
          </Checkbox>
          <Button onClick={() => setParams({ page: 1, pageSize: 20 })}>重置</Button>
        </Space>
        <Table<LogisticsException>
          columns={columns}
          dataSource={listQuery.data?.items ?? []}
          loading={listQuery.isLoading}
          pagination={{
            current: params.page,
            pageSize: params.pageSize,
            total: listQuery.data?.total ?? 0,
            onChange: (page) => setParams((current) => ({ ...current, page })),
          }}
          rowKey="id"
        />
      </Card>
      <LogisticsExceptionDrawer
        actionLoading={actionMutation.isPending}
        canManage={canManage}
        canOperate={canOperate}
        loading={detailQuery.isLoading}
        onAction={runAction}
        onClose={() => setSelectedId(null)}
        open={Boolean(selectedId)}
        record={detailQuery.data}
      />
    </Space>
  )
}
