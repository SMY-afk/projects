import { ArrowLeftOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Result, Space, Spin, Steps, Table, Tag, Typography } from 'antd'
import { Link, useNavigate, useParams } from 'react-router'
import { LogisticsSectionNav } from '../components/logistics-section-nav'
import { getReturnFlowState, returnFlowSteps } from '../components/return-flow'
import { useReturnRequestQuery, useReturnShopsQuery } from '../queries/returns.queries'
import type { ReturnRequestItem, ReturnRequestStatus, ReturnRequestType } from '../types/returns.types'
import './logistics-page.css'

const typeLabels: Record<ReturnRequestType, string> = { return: '退货', exchange: '换货', refund: '仅退款' }
const statusLabels: Record<ReturnRequestStatus, string> = {
  pending_review: '待审核',
  approved: '已批准',
  rejected: '已拒绝',
  cancelled: '已取消',
}

const displayTime = (value: string | null) => (value ? new Date(value).toLocaleString() : '-')

export default function ReturnDetailPage() {
  const { requestId = '' } = useParams()
  const navigate = useNavigate()
  const query = useReturnRequestQuery(requestId)
  const shopsQuery = useReturnShopsQuery()

  if (query.isLoading) return <Spin />
  if (query.isError || !query.data) return <Result status="error" title="退换货详情加载失败" />

  const record = query.data
  const flow = getReturnFlowState(record)
  const shopName = shopsQuery.data?.find((shop) => shop.id === record.shopId)?.shopName ?? record.shopId

  return (
    <Space className="logistics-page logistics-detail-page" orientation="vertical" size="large">
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate('/logistics/returns')}>
        返回退换货列表
      </Button>
      <LogisticsSectionNav />
      <div>
        <Typography.Title level={3}>{record.requestNumber}</Typography.Title>
        <Space>
          <Tag color={record.status === 'approved' ? 'green' : 'blue'}>{statusLabels[record.status]}</Tag>
          <Typography.Text type="secondary">原订单：{record.orderNumber}</Typography.Text>
        </Space>
      </div>

      <Card title="退换货流程">
        <Steps
          current={flow.current}
          items={returnFlowSteps.map((title) => ({ title }))}
          responsive
          size="small"
          status={flow.status}
        />
        <Typography.Text type="secondary">当前判断：{flow.basis}</Typography.Text>
      </Card>

      <Alert
        showIcon
        type="info"
        message="库存边界"
        description="质检和最终处置仅展示现有平台/RMA状态；本期不创建库存入库、扣减或自动入库记录。"
      />

      <Card title="申请信息">
        <Descriptions
          bordered
          column={{ xs: 1, sm: 2, lg: 3 }}
          items={[
            { label: '店铺', children: shopName },
            { label: '类型', children: typeLabels[record.requestType] },
            { label: '状态', children: statusLabels[record.status] },
            { label: '原因代码', children: record.reasonCode },
            { label: '平台原因', children: record.platformReasonText ?? '-' },
            { label: '申请时间', children: displayTime(record.platformCreatedAt ?? record.createdAt) },
            { label: '来源', children: record.source === 'platform' ? 'TikTok' : 'ERP' },
            { label: '平台状态', children: record.platformStatus ?? '-' },
            {
              label: '原销售订单',
              children: <Link to={`/orders/${record.orderId}`}>{record.orderNumber}</Link>,
            },
          ]}
        />
      </Card>

      <Card title="审核信息">
        <Descriptions
          bordered
          column={{ xs: 1, sm: 2 }}
          items={[
            { label: '审核时间', children: displayTime(record.reviewedAt) },
            { label: '审核人', children: record.reviewedByUserId ?? '-' },
            { label: '审核备注', children: record.reviewNote ?? '-' },
            { label: '客户备注', children: record.customerNote ?? '-' },
          ]}
        />
      </Card>

      <Card title="申请商品">
        <Table<ReturnRequestItem>
          dataSource={record.items}
          pagination={false}
          rowKey="id"
          columns={[
            { title: '商品', dataIndex: 'productName' },
            { title: '规格', dataIndex: 'skuName', render: (value: string | null) => value ?? '-' },
            { title: '商家 SKU', dataIndex: 'sellerSku', render: (value: string | null) => value ?? '-' },
            { title: '申请数量', dataIndex: 'requestedQuantity' },
            { title: '原因', dataIndex: 'reasonCode' },
          ]}
        />
      </Card>

      <Card title="RMA 与逆向物流">
        <Descriptions
          bordered
          column={{ xs: 1, sm: 2 }}
          items={[
            { label: 'RMA 编号', children: record.rma?.rmaNumber ?? '-' },
            { label: 'RMA 状态', children: record.rma?.status ?? '-' },
            { label: '生成时间', children: displayTime(record.rma?.generatedAt ?? null) },
            {
              label: '逆向物流任务',
              children: record.rma?.reverseTaskId ? (
                <Link to={`/logistics/tasks/${record.rma.reverseTaskId}`}>查看逆向物流任务</Link>
              ) : (
                '-'
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
