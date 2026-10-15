import { ArrowLeftOutlined, EyeOutlined } from '@ant-design/icons'
import { App, Button, Card, Descriptions, Result, Space, Spin, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import { logisticsApi } from '../api/logistics.api'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import { LogisticsStatusSteps } from '../components/logistics-status-steps'
import {
  useConfirmPickingMutation,
  useLogisticsOrderContextQuery,
  useLogisticsPackagesQuery,
  useLogisticsTaskQuery,
} from '../queries/logistics.queries'
import type { LogisticsRecipient, LogisticsTaskItem, LogisticsTaskReview } from '../types/logistics.types'
import './logistics-page.css'

export default function LogisticsTaskDetailPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermissions } = useAuth()
  const taskQuery = useLogisticsTaskQuery(taskId)
  const task = taskQuery.data
  const orderQuery = useLogisticsOrderContextQuery(taskId, Boolean(task?.orderId))
  const packageQuery = useLogisticsPackagesQuery(taskId)
  const pickingMutation = useConfirmPickingMutation(taskId)
  const [recipient, setRecipient] = useState<LogisticsRecipient | null>(null)
  const [recexampled14e2df5, setRecipientLoading] = useState(false)

  if (taskQuery.isLoading) return <Spin />
  if (taskQuery.isError || !task) return <Result status="error" title="物流任务加载失败" />
  const canOperate = hasPermissions([modulePermissionCodes.logisticsOperate])
  const canViewPii = hasPermissions([modulePermissionCodes.ordersBuyerPiiView])
  const pickingOperation = task.operations.find((item) => item.operationType === 'picking_completed')
  const canConfirmPicking = canOperate && task.status === 'pending_review' && !pickingOperation
  const canReview = canOperate && task.status === 'pending_review' && Boolean(pickingOperation)
  const canPack = canOperate && ['pending_pack', 'pending_waybill'].includes(task.status)
  const canDispatch = hasPermissions([modulePermissionCodes.logisticsDispatch])
  const canCreateWaybill = canDispatch && ['pending_waybill', 'pending_dispatch'].includes(task.status)
  const maskedRecipient = orderQuery.data?.maskedRecipient

  const confirmPicking = async () => {
    try {
      await pickingMutation.mutateAsync()
      void message.success('已人工确认配货完成')
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '确认配货完成失败')
    }
  }

  const revealRecipient = async () => {
    if (!task.orderId) return
    setRecipientLoading(true)
    try {
      setRecipient(await logisticsApi.getRecipient(task.orderId))
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '完整收件信息加载失败')
    } finally {
      setRecipientLoading(false)
    }
  }

  return (
    <Space className="logistics-page logistics-detail-page" orientation="vertical" size="large">
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate('/logistics')}>
        返回任务中心
      </Button>
      <LogisticsSectionNav />
      <div>
        <Typography.Title level={3}>{task.taskNumber}</Typography.Title>
        <Typography.Text type="secondary">来源单号：{task.sourceNumber}</Typography.Text>
      </div>
      <Card title="物流状态">
        <LogisticsStatusSteps status={task.status} />
      </Card>

      <div className="logistics-detail-grid">
        <section className="logistics-detail-main">
          <Card title="任务商品">
            <Table<LogisticsTaskItem>
              dataSource={task.items}
              pagination={false}
              rowKey="id"
              columns={[
                { title: '商品', dataIndex: 'productName' },
                { title: '规格', dataIndex: 'skuName', render: (value: string | null) => value ?? '-' },
                { title: '商家 SKU', dataIndex: 'sellerSku', render: (value: string | null) => value ?? '-' },
                { title: '计划', dataIndex: 'plannedQuantity' },
                { title: '已包装', dataIndex: 'packedQuantity' },
                { title: '已发货', dataIndex: 'shippedQuantity' },
              ]}
            />
          </Card>
          <Card title="复核记录">
            <Table<LogisticsTaskReview>
              dataSource={task.reviews}
              locale={{ emptyText: pickingOperation ? '等待提交复核' : '等待配货完成' }}
              pagination={false}
              rowKey="id"
              columns={[
                { title: '结果', dataIndex: 'result' },
                { title: '应复核', dataIndex: 'expectedQuantity' },
                { title: '实盘', dataIndex: 'actualQuantity' },
                { title: '差异项', render: (_, review) => review.differences.length },
                { title: '操作员', dataIndex: 'reviewerUserId' },
                { title: '时间', dataIndex: 'reviewedAt', render: (value: string) => new Date(value).toLocaleString() },
              ]}
            />
          </Card>
        </section>

        <aside className="logistics-detail-aside">
          <Card loading={orderQuery.isLoading} title="订单信息">
            <Descriptions
              column={1}
              items={[
                { label: '订单号', children: orderQuery.data?.orderNumber ?? task.sourceNumber },
                { label: '店铺', children: orderQuery.data?.shopName ?? '-' },
                { label: '订单状态', children: orderQuery.data?.externalStatus ?? '-' },
                { label: '买家', children: orderQuery.data?.buyerUsernameMasked ?? '-' },
                {
                  label: '下单时间',
                  children: orderQuery.data?.placedAt ? new Date(orderQuery.data.placedAt).toLocaleString() : '-',
                },
                { label: '优先级', children: <Tag>{task.priority}</Tag> },
              ]}
            />
          </Card>
          <Card
            extra={
              canViewPii && task.orderId ? (
                <Button icon={<EyeOutlined />} loading={recexampled14e2df5} onClick={() => void revealRecipient()}>
                  查看完整信息
                </Button>
              ) : null
            }
            title="收件信息"
          >
            <Descriptions
              column={1}
              items={[
                { label: '收件人', children: recipient?.name ?? maskedRecipient?.name ?? '-' },
                { label: '电话', children: recipient?.phone ?? maskedRecipient?.phone ?? '-' },
                { label: '地址', children: recipient?.address ?? maskedRecipient?.address ?? '-' },
                { label: '国家/地区', children: recipient?.countryCode ?? maskedRecipient?.countryCode ?? '-' },
              ]}
            />
            {!canViewPii && <Typography.Text type="secondary">完整信息需要订单买家隐私查看权限。</Typography.Text>}
          </Card>
          <Card title="包裹概况">
            <Descriptions
              column={1}
              items={[
                { label: '包裹数', children: packageQuery.data?.length ?? 0 },
                { label: '草稿', children: packageQuery.data?.filter((item) => item.status === 'draft').length ?? 0 },
                {
                  label: '已封箱',
                  children: packageQuery.data?.filter((item) => item.status === 'packed').length ?? 0,
                },
              ]}
            />
          </Card>
        </aside>
      </div>

      <div className="logistics-action-bar">
        <Space>
          <Tag color={pickingOperation ? 'green' : 'default'}>{pickingOperation ? '配货已完成' : '待配货确认'}</Tag>
          {canConfirmPicking && (
            <Button loading={pickingMutation.isPending} onClick={() => void confirmPicking()}>
              确认配货完成
            </Button>
          )}
          {canReview && <Button onClick={() => void navigate(`/logistics/tasks/${taskId}/review`)}>扫码复核</Button>}
          {canPack && (
            <Button type="primary" onClick={() => void navigate(`/logistics/tasks/${taskId}/packages/new`)}>
              打开打包面板
            </Button>
          )}
          {canCreateWaybill && (
            <Button type="primary" onClick={() => void navigate(`/logistics/tasks/${taskId}/shipping`)}>
              选择物流与运单
            </Button>
          )}
        </Space>
      </div>
    </Space>
  )
}
