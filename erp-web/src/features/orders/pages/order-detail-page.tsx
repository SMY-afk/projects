import { ArrowLeftOutlined, EyeOutlined, RetweetOutlined, SendOutlined } from '@ant-design/icons'
import { App, Button, Card, Descriptions, Result, Space, Spin, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { useAuth } from '@/auth/use-auth'
import { logisticsApi } from '@/features/logistics/api/logistics.api'
import { orderApi } from '../api/order.api'
import {
  AFFILIATE_EVIDENCE_LABEL,
  formatAttributionDimension,
  formatAffiliateCommission,
  formatFulfillmentStatus,
  formatMoney,
  getAffiliateOrderDisplay,
  UNKNOWN_ATTRIBUTION_LABEL,
} from '../components/order-format'
import { useOrderDetailQuery } from '../queries/order.queries'
import type { OrderRecipient } from '../types/order.types'
import '../components/order-list.css'

export default function OrderDetailPage() {
  const { orderId = '' } = useParams()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermissions } = useAuth()
  const [recipient, setRecipient] = useState<OrderRecipient | null>(null)
  const [recexampled14e2df5, setRecipientLoading] = useState(false)
  const [taskLoading, setTaskLoading] = useState(false)
  const query = useOrderDetailQuery(orderId)
  if (query.isLoading) return <Spin />
  if (query.isError || !query.data) return <Result status="error" title="订单详情加载失败" />
  const order = query.data
  const attributionEvidence = order.attribution.evidenceSummary
  const affiliate = getAffiliateOrderDisplay(order.affiliateItems)
  const attributionStatusLabel = affiliate
    ? AFFILIATE_EVIDENCE_LABEL
    : order.attribution.classificationStatus === 'confirmed'
      ? '确认'
      : order.attribution.classificationStatus === 'derived'
        ? '推导'
        : UNKNOWN_ATTRIBUTION_LABEL
  const canViewPii = hasPermissions([modulePermissionCodes.ordersBuyerPiiView])
  const canGenerateTask =
    order.status === 'awaiting_shipment' &&
    order.lines.length > 0 &&
    hasPermissions([modulePermissionCodes.logisticsOperate])
  const canCreateReturn = order.lines.length > 0 && hasPermissions([modulePermissionCodes.returnsManage])
  const generateTask = async () => {
    setTaskLoading(true)
    try {
      const result = await logisticsApi.generateTasks({
        orderId: order.id,
        tasks: [
          {
            items: order.lines.map((line) => ({
              orderLineId: line.id,
              plannedQuantity: line.quantity,
            })),
            priority: 'normal',
            note: '从销售订单详情生成',
          },
        ],
      })
      const task = result.items[0]
      if (!task) throw new Error('物流任务创建后未返回任务记录')
      void message.success('物流任务已生成')
      void navigate(`/logistics/tasks/${task.id}`)
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '物流任务生成失败')
    } finally {
      setTaskLoading(false)
    }
  }
  const revealRecipient = async () => {
    setRecipientLoading(true)
    try {
      setRecipient(await orderApi.getRecipient(orderId))
    } catch (error) {
      void message.error(error instanceof Error ? error.message : '收件信息加载失败')
    } finally {
      setRecipientLoading(false)
    }
  }
  return (
    <section style={{ padding: 24 }}>
      <Button icon={<ArrowLeftOutlined />} onClick={() => void navigate('/orders')} style={{ marginBottom: 16 }}>
        返回订单列表
      </Button>
      <Space align="center">
        <Typography.Title level={4}>{order.orderNumber}</Typography.Title>
        {canGenerateTask && (
          <Button type="primary" icon={<SendOutlined />} loading={taskLoading} onClick={() => void generateTask()}>
            生成物流任务
          </Button>
        )}
        {canCreateReturn && (
          <Button icon={<RetweetOutlined />} onClick={() => void navigate(`/logistics/returns?orderId=${order.id}`)}>
            申请退换货
          </Button>
        )}
      </Space>
      <Descriptions
        bordered
        className="order-detail-section"
        column={2}
        items={[
          { label: '店铺', children: order.shopName },
          { label: '平台状态', children: order.externalStatus },
          { label: '订单金额', children: formatMoney(order.totalAmountMinor, order.currency) },
          { label: '商品小计', children: formatMoney(order.subtotalAmountMinor, order.currency) },
          { label: '运费', children: formatMoney(order.shippingFeeMinor, order.currency) },
          { label: '优惠', children: formatMoney(order.discountAmountMinor, order.currency) },
          { label: '税费', children: formatMoney(order.taxAmountMinor, order.currency) },
          { label: '同步时间', children: new Date(order.syncedAt).toLocaleString() },
        ]}
      />
      <Card className="order-detail-section" title="成交链路">
        <Descriptions bordered column={2}>
          <Descriptions.Item label="完整路径">
            {affiliate?.chainLabel ?? formatAttributionDimension(order.attribution.chainCode)}
          </Descriptions.Item>
          <Descriptions.Item label="判定状态">
            <Tag color={affiliate ? 'cyan' : order.attribution.classificationStatus === 'unknown' ? 'warning' : 'blue'}>
              {attributionStatusLabel}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="判定方法">{order.attribution.classificationMethod}</Descriptions.Item>
          <Descriptions.Item label="判定时间">
            {order.attribution.sourceUpdatedAt ? new Date(order.attribution.sourceUpdatedAt).toLocaleString() : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="归类原因">
            {affiliate
              ? 'main_order_id 已精确关联联盟订单；平台响应未提供视频、直播或橱窗入口枚举'
              : (attributionEvidence[0]?.reasonLabel ?? UNKNOWN_ATTRIBUTION_LABEL)}
          </Descriptions.Item>
          <Descriptions.Item label="流量来源">
            {formatAttributionDimension(order.attribution.trafficSource)}
          </Descriptions.Item>
          <Descriptions.Item label="经营主体">
            {formatAttributionDimension(order.attribution.operatorSubject)}
          </Descriptions.Item>
          <Descriptions.Item label="成交入口">
            {formatAttributionDimension(order.attribution.entryPoint)}
          </Descriptions.Item>
          <Descriptions.Item label="特殊订单类型">
            {formatAttributionDimension(order.attribution.specialOrderType)}
          </Descriptions.Item>
        </Descriptions>
        <Typography.Title level={5} style={{ marginTop: 20 }}>
          安全证据摘要
        </Typography.Title>
        <Table
          columns={[
            { title: '来源', dataIndex: 'source' },
            { title: '字段', dataIndex: 'fieldPath' },
            { title: '脱敏值', dataIndex: 'value' },
            { title: '强度', dataIndex: 'strength' },
            { title: '原因', dataIndex: 'reasonLabel' },
          ]}
          dataSource={attributionEvidence}
          locale={{ emptyText: '暂无脱敏证据摘要' }}
          pagination={false}
          rowKey={(evidence) => `${evidence.source}-${evidence.fieldPath}-${evidence.reason}`}
        />
      </Card>
      {affiliate && (
        <Card className="order-detail-section" title={`联盟订单数据（${affiliate.itemCount} 个 SKU）`}>
          <Table
            columns={[
              {
                title: '达人',
                render: (_, item) => item.creatorNickname || item.creatorId || '-',
              },
              {
                title: '商品',
                render: (_, item) => item.productName || item.productId,
              },
              { title: 'SKU', render: (_, item) => item.skuName || item.skuId },
              {
                title: '佣金率',
                render: (_, item) =>
                  item.commissionRate == null ? '-' : `${(Number(item.commissionRate) * 100).toFixed(2)}%`,
              },
              {
                title: '预计佣金',
                render: (_, item) => formatAffiliateCommission([item]),
              },
            ]}
            dataSource={order.affiliateItems}
            pagination={false}
            rowKey={(item) => `${item.mainOrderId}-${item.skuId}`}
          />
        </Card>
      )}
      <Typography.Title level={5}>订单商品</Typography.Title>
      <Table
        columns={[
          { title: '商品', dataIndex: 'productName' },
          { title: 'SKU', dataIndex: 'sellerSku' },
          { title: '数量', dataIndex: 'quantity' },
          { title: '成交单价', render: (_, line) => formatMoney(line.saleUnitPriceMinor, order.currency) },
          { title: '小计', render: (_, line) => formatMoney(line.lineTotalAmountMinor, order.currency) },
        ]}
        dataSource={order.lines}
        pagination={false}
        rowKey="id"
      />
      <Typography.Title level={5} style={{ marginTop: 24 }}>
        物流信息
      </Typography.Title>
      <Table
        columns={[
          { title: '包裹 ID', dataIndex: 'platformPackageId' },
          {
            title: '状态',
            dataIndex: 'status',
            render: (value: string) => <span title={value}>{formatFulfillmentStatus(value)}</span>,
          },
          { title: '承运商', dataIndex: 'carrier' },
          { title: '运单号', dataIndex: 'trackingNumberMasked' },
        ]}
        dataSource={order.fulfillments}
        locale={{ emptyText: '暂无物流信息' }}
        pagination={false}
        rowKey="id"
      />
      <Typography.Title level={5} style={{ marginTop: 24 }}>
        收件信息
      </Typography.Title>
      <Descriptions
        bordered
        column={1}
        items={[
          { label: '收件人', children: recipient?.name ?? order.maskedRecipient?.name ?? '-' },
          { label: '电话', children: recipient?.phone ?? order.maskedRecipient?.phone ?? '-' },
          { label: '地址', children: recipient?.address ?? order.maskedRecipient?.address ?? '-' },
        ]}
      />
      {canViewPii && !order.maskedRecipient?.purged && !recipient && (
        <div className="order-recipient-actions">
          <Button icon={<EyeOutlined />} loading={recexampled14e2df5} onClick={() => void revealRecipient()}>
            查看完整收件信息
          </Button>
          <Typography.Text type="secondary">本次访问将记录安全审计</Typography.Text>
        </div>
      )}
      {recipient && (
        <Space style={{ marginTop: 12 }}>
          <Typography.Text type="warning">请仅将该信息用于履约处理，离开页面后不会缓存。</Typography.Text>
        </Space>
      )}
    </section>
  )
}
