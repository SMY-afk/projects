import { PlusOutlined, SyncOutlined } from '@ant-design/icons'
import { App, Button, Card, Space, Steps, Table, Tag, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import { returnFlowSteps } from '../components/return-flow'
import { ReturnListFilters } from '../components/return-list-filters'
import { ReturnRequestModal } from '../components/return-request-modal'
import {
  useReturnRequestsQuery,
  useReturnShopsQuery,
  useReviewReturnRequestMutation,
  useSyncReturnRequestsMutation,
} from '../queries/returns.queries'
import type { ReturnRequestRecord, ReturnRequestStatus, ReturnRequestType } from '../types/returns.types'
import './logistics-page.css'

const returnStatusLabels: Record<ReturnRequestStatus, string> = {
  pending_review: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
}
const statusColors: Record<ReturnRequestStatus, string> = {
  pending_review: 'processing',
  approved: 'success',
  rejected: 'error',
  cancelled: 'default',
}

export default function ReturnsPage() {
  const { message, modal } = App.useApp()
  const { hasPermissions } = useAuth()
  const [searchParams] = useSearchParams()
  const [createOpen, setCreateOpen] = useState(Boolean(searchParams.get('orderId')))
  const [status, setStatus] = useState<ReturnRequestStatus>()
  const [requestType, setRequestType] = useState<ReturnRequestType>()
  const [page, setPage] = useState(1)
  const [shopId, setShopId] = useState<string>()
  const [reason, setReason] = useState('')
  const [rma, setRma] = useState('')
  const [appliedRange, setAppliedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const canManage = hasPermissions([modulePermissionCodes.returnsManage])
  const params = useMemo(
    () => ({
      page,
      pageSize: 20,
      shopId,
      status,
      requestType,
      reason: reason.trim() || undefined,
      rma: rma.trim() || undefined,
      appliedFrom: appliedRange?.[0]?.startOf('day').toISOString(),
      appliedTo: appliedRange?.[1]?.endOf('day').toISOString(),
    }),
    [appliedRange, page, reason, requestType, rma, shopId, status],
  )
  const query = useReturnRequestsQuery(params)
  const shopsQuery = useReturnShopsQuery()
  const shopNames = useMemo(
    () => new Map((shopsQuery.data ?? []).map((shop) => [shop.id, shop.shopName])),
    [shopsQuery.data],
  )
  const selectedShopId = shopId ?? shopsQuery.data?.[0]?.id
  const reviewMutation = useReviewReturnRequestMutation()
  const syncMutation = useSyncReturnRequestsMutation()

  const syncReturns = async () => {
    if (!selectedShopId) {
      void message.warning('暂无可同步的真实店铺')
      return
    }
    try {
      const result = await syncMutation.mutateAsync(selectedShopId)
      void message.success(
        `已读取 ${result.fetchedCount} 条，写入 ${result.upsertedCount} 条；${result.unmatchedOrderCount + result.unmatchedLineCount} 条因原订单或订单行缺失未导入`,
      )
    } catch (error) {
      void message.error(error instanceof Error ? error.message : 'TikTok 退换货同步失败')
    }
  }

  const review = (record: ReturnRequestRecord, decision: 'approve' | 'reject') => {
    modal.confirm({
      title: decision === 'approve' ? '批准退换货申请' : '拒绝退换货申请',
      content:
        decision === 'approve'
          ? '批准后将生成 RMA 和逆向物流任务，但不会自动生成运单号。'
          : '拒绝后将释放该申请占用的最大可退数量。',
      okText: decision === 'approve' ? '确认批准' : '确认拒绝',
      okButtonProps: { danger: decision === 'reject' },
      onOk: async () => {
        try {
          await reviewMutation.mutateAsync({
            requestId: record.id,
            data: { decision, versionId: record.versionId, note: null },
          })
          void message.success(decision === 'approve' ? '已生成 RMA 和逆向物流任务' : '申请已拒绝')
        } catch (error) {
          void message.error(error instanceof Error ? error.message : '审核失败')
          throw error
        }
      },
    })
  }

  const resetFilters = () => {
    setShopId(undefined)
    setStatus(undefined)
    setRequestType(undefined)
    setReason('')
    setRma('')
    setAppliedRange(null)
    setPage(1)
  }

  return (
    <Space className="logistics-page" orientation="vertical" size="large">
      <div>
        <Typography.Title level={2}>退换货与逆向物流</Typography.Title>
        <Typography.Text type="secondary">
          基于原销售订单控制最大可退数量；审核通过后生成 RMA，并复用包裹、承运商、运单和轨迹能力。
        </Typography.Text>
      </div>
      <LogisticsSectionNav />
      <Card title="逆向物流流程">
        <Steps current={0} items={returnFlowSteps.map((title) => ({ title }))} responsive size="small" />
      </Card>
      <Card
        title="退换货申请"
        extra={
          canManage && (
            <Space>
              <Button icon={<SyncOutlined />} loading={syncMutation.isPending} onClick={() => void syncReturns()}>
                同步 TikTok
              </Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                创建申请
              </Button>
            </Space>
          )
        }
      >
        <ReturnListFilters
          appliedRange={appliedRange}
          onAppliedRangeChange={(value) => {
            setAppliedRange(value)
            setPage(1)
          }}
          onReasonChange={(value) => {
            setReason(value)
            setPage(1)
          }}
          onReset={resetFilters}
          onRmaChange={(value) => {
            setRma(value)
            setPage(1)
          }}
          onShopChange={(value) => {
            setShopId(value)
            setPage(1)
          }}
          onStatusChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
          onTypeChange={(value) => {
            setRequestType(value)
            setPage(1)
          }}
          reason={reason}
          requestType={requestType}
          rma={rma}
          shopId={shopId}
          shops={shopsQuery.data ?? []}
          shopsLoading={shopsQuery.isLoading}
          status={status}
        />
        <Table<ReturnRequestRecord>
          rowKey="id"
          loading={query.isLoading}
          dataSource={query.data?.items ?? []}
          pagination={{
            current: page,
            pageSize: 20,
            total: query.data?.total ?? 0,
            onChange: setPage,
          }}
          columns={[
            {
              title: '申请编号',
              dataIndex: 'requestNumber',
              render: (value: string, record) => <Link to={`/logistics/returns/${record.id}`}>{value}</Link>,
            },
            { title: '店铺', dataIndex: 'shopId', render: (value: string) => shopNames.get(value) ?? value },
            { title: '原订单', dataIndex: 'orderNumber' },
            {
              title: '类型',
              dataIndex: 'requestType',
              render: (value: ReturnRequestType) => ({ return: '退货', exchange: '换货', refund: '仅退款' })[value],
            },
            {
              title: '来源 / 平台状态',
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <Tag color={record.source === 'platform' ? 'blue' : 'default'}>
                    {record.source === 'platform' ? 'TikTok' : 'ERP'}
                  </Tag>
                  {record.platformStatus && (
                    <Typography.Text type="secondary">{record.platformStatus.replaceAll('_', ' ')}</Typography.Text>
                  )}
                </Space>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: ReturnRequestStatus) => (
                <Tag color={statusColors[value]}>{returnStatusLabels[value]}</Tag>
              ),
            },
            {
              title: '原因',
              render: (_, record) => record.platformReasonText ?? record.reasonCode,
            },
            {
              title: '申请数量',
              render: (_, record) => record.items.reduce((sum, item) => sum + item.requestedQuantity, 0),
            },
            {
              title: 'RMA / 逆向任务',
              render: (_, record) =>
                record.rma ? (
                  <Space direction="vertical" size={0}>
                    <span>{record.rma.rmaNumber}</span>
                    {record.rma.reverseTaskId && (
                      <Link to={`/logistics/tasks/${record.rma.reverseTaskId}`}>查看逆向物流任务</Link>
                    )}
                  </Space>
                ) : (
                  '-'
                ),
            },
            {
              title: '申请时间',
              render: (_, record) => new Date(record.platformCreatedAt ?? record.createdAt).toLocaleString(),
            },
            {
              title: '操作',
              render: (_, record) => (
                <Space>
                  <Link to={`/logistics/returns/${record.id}`}>查看</Link>
                  {canManage && record.source === 'local' && record.status === 'pending_review' && (
                    <>
                      <Button type="link" onClick={() => review(record, 'approve')}>
                        批准
                      </Button>
                      <Button danger type="link" onClick={() => review(record, 'reject')}>
                        拒绝
                      </Button>
                    </>
                  )}
                </Space>
              ),
            },
          ]}
          locale={{ emptyText: query.isError ? '退换货列表加载失败' : '暂无退换货申请' }}
        />
      </Card>
      <ReturnRequestModal
        open={createOpen}
        initialOrderReference={searchParams.get('orderId') ?? ''}
        onClose={() => setCreateOpen(false)}
      />
    </Space>
  )
}
