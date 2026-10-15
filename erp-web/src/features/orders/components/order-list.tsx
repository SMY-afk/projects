import { PlayCircleOutlined } from '@ant-design/icons'
import { Select, Space, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { modulePermissionCodes } from '@/auth/permission-codes'
import { ErpListPage } from '@/shared/components/erp-list/erp-list-page'
import type {
  AffiliateContentForm,
  OrderAttributionFilterKey,
  OrderListParams,
  OrderShopOption,
  OrderStatus,
  OrderSummary,
} from '../types/order.types'
import { OrderChainFilter } from './order-chain-filter'
import { OrderContentFormFilter } from './order-content-form-filter'
import {
  AFFILIATE_EVIDENCE_LABEL,
  formatAttributionDimension,
  formatFulfillmentStatus,
  formatMoney,
  getAffiliateContentFormLabels,
  getAffiliateOrderDisplay,
  getAffiliateVideoIds,
  getOrderCreatorDisplay,
  getSampleOrderLabel,
  UNKNOWN_ATTRIBUTION_LABEL,
} from './order-format'
import './order-list.css'

const statusLabels: Record<OrderStatus, string> = {
  unpaid: '待付款',
  on_hold: '暂停',
  awaiting_shipment: '待发货',
  awaiting_collection: '待揽收',
  partially_shipped: '部分发货',
  in_transit: '运输中',
  delivered: '已送达',
  completed: '已完成',
  cancelled: '已取消',
  unknown: '未知状态',
}

const statusOptions = Object.entries(statusLabels).map(([value, label]) => ({ value, label }))

const attributionStatusLabels: Record<string, string> = {
  confirmed: '已确认',
  derived: '已推导',
  unknown: UNKNOWN_ATTRIBUTION_LABEL,
}

export function OrderList({
  data,
  pagination,
  shopOptions,
  selectedShopId,
  onPageChange,
  onSearchChange,
  onStatusChange,
  onShopChange,
  onOpenDetail,
  onAttributionChange,
  onOrderTypeChange,
  onReset,
  selectedOrderTypePath,
  selectedContentForm,
  onContentFormChange,
}: {
  data: OrderSummary[]
  pagination: { current: number; pageSize: number; total: number }
  shopOptions: OrderShopOption[]
  selectedShopId?: string
  onPageChange: (page: number, pageSize: number) => void
  onSearchChange: (keyword: string) => void
  onStatusChange: (status?: OrderStatus) => void
  onShopChange: (shopId?: string) => void
  onOpenDetail: (orderId: string) => void
  onAttributionChange: (field: OrderAttributionFilterKey, value?: string) => void
  onOrderTypeChange: (path?: string[]) => void
  onReset?: () => void
  selectedOrderTypePath?: string[]
  selectedContentForm?: AffiliateContentForm
  onContentFormChange: (value?: AffiliateContentForm) => void
}) {
  const columns: ColumnsType<OrderSummary> = [
    {
      title: '订单号',
      dataIndex: 'orderNumber',
      width: 230,
      ellipsis: true,
      render: (value: string) => <Typography.Text copyable>{value}</Typography.Text>,
    },
    { title: '店铺', dataIndex: 'shopName', width: 160 },
    {
      title: '买家',
      dataIndex: 'buyerUsernameMasked',
      width: 190,
      ellipsis: true,
      render: (value: string | null | undefined) => value ?? '-',
    },
    { title: '商品', dataIndex: 'itemSummary', width: 220, ellipsis: true },
    {
      title: '金额',
      width: 130,
      align: 'right',
      render: (_, order) => formatMoney(order.totalAmountMinor, order.currency),
    },
    {
      title: '结算金额',
      width: 130,
      align: 'right',
      render: (_, order) =>
        order.settlementAmountMinor == null ? '--' : formatMoney(order.settlementAmountMinor, order.currency),
    },
    {
      title: '订单状态',
      dataIndex: 'status',
      width: 110,
      render: (value: OrderStatus) => (
        <Tag color={value === 'cancelled' ? 'default' : value === 'unknown' ? 'warning' : 'green'}>
          {statusLabels[value]}
        </Tag>
      ),
    },
    {
      title: '物流状态',
      dataIndex: 'fulfillmentStatus',
      width: 110,
      render: (value: string) => <span title={value}>{formatFulfillmentStatus(value)}</span>,
    },
    {
      key: 'transactionChain',
      title: <OrderChainFilter value={selectedOrderTypePath} onChange={onOrderTypeChange} />,
      width: 340,
      render: (_, order) => {
        const affiliate = getAffiliateOrderDisplay(order.affiliateItems)
        const creator = getOrderCreatorDisplay(order.attribution)
        const sampleLabel = getSampleOrderLabel(order)
        return (
          <div className="order-attribution-cell">
            {sampleLabel ? (
              <Tag
                className="order-sample-tag"
                color={sampleLabel === '联盟样品订单' ? 'magenta' : sampleLabel === '自家样品订单' ? 'purple' : 'gold'}
              >
                {sampleLabel}
              </Tag>
            ) : null}
            {affiliate ? (
              <div title={`${affiliate.creatorLabel} · ${affiliate.commissionLabel}`}>
                <Typography.Text>{affiliate.chainLabel}</Typography.Text>
                <br />
                <Typography.Text type="secondary">
                  {affiliate.creatorLabel} · {affiliate.commissionLabel}
                </Typography.Text>
              </div>
            ) : (
              <Typography.Text
                title={formatAttributionDimension(order.attribution.chainCode)}
                type={order.attribution.chainCode === 'unknown' ? 'secondary' : undefined}
              >
                {formatAttributionDimension(order.attribution.chainCode)}
              </Typography.Text>
            )}
            {creator ? (
              <div className="order-creator-account">
                {creator.alias ? (
                  <Tag className="order-creator-handle" color="cyan">
                    {creator.alias}
                  </Tag>
                ) : (
                  <Typography.Text type="secondary">别名待同步</Typography.Text>
                )}
                {creator.creatorId ? (
                  <div className="order-creator-id">
                    <span className="order-creator-id-label">Creator ID</span>
                    <Typography.Text
                      className="order-creator-id-value"
                      copyable={{ text: creator.creatorId, tooltips: ['复制 Creator ID', '已复制'] }}
                      ellipsis={{ tooltip: creator.creatorId }}
                    >
                      {creator.creatorId}
                    </Typography.Text>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )
      },
    },
    {
      title: <OrderContentFormFilter value={selectedContentForm} onChange={onContentFormChange} />,
      width: 250,
      render: (_, order) => {
        const labels = getAffiliateContentFormLabels(order.affiliateItems)
        const videoIds = getAffiliateVideoIds(order.affiliateItems)
        if (!labels.length) return <Typography.Text type="secondary">-</Typography.Text>
        return (
          <div className="order-content-form">
            <Space size={[4, 4]} wrap>
              {labels.map((label) => (
                <Tag color="cyan" icon={label === '视频' ? <PlayCircleOutlined /> : undefined} key={label}>
                  {label}
                </Tag>
              ))}
            </Space>
            {videoIds.map((videoId) => (
              <div className="order-video-id" key={videoId}>
                <span className="order-video-id-label">视频 ID</span>
                <Typography.Text
                  className="order-video-id-value"
                  copyable={{ text: videoId, tooltips: ['复制视频 ID', '已复制'] }}
                  ellipsis={{ tooltip: videoId }}
                >
                  {videoId}
                </Typography.Text>
              </div>
            ))}
          </div>
        )
      },
    },
    {
      title: '判定状态',
      width: 190,
      render: (_, order) => {
        if (order.affiliateItems.length) {
          return <Tag color="cyan">{AFFILIATE_EVIDENCE_LABEL}</Tag>
        }
        return (
          <Tag color={order.attribution.classificationStatus === 'unknown' ? 'warning' : 'blue'}>
            {attributionStatusLabels[order.attribution.classificationStatus] ?? UNKNOWN_ATTRIBUTION_LABEL}
          </Tag>
        )
      },
    },
    {
      title: '下单时间',
      dataIndex: 'placedAt',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: '更新时间',
      dataIndex: 'platformUpdatedAt',
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
  ]
  const attributionFilter = (
    field: keyof Pick<
      OrderListParams,
      'trafficSource' | 'operatorSubject' | 'entryPoint' | 'specialOrderType' | 'classificationStatus'
    >,
    placeholder: string,
    options: { value: string; label: string }[],
  ) => (
    <Select
      allowClear
      onChange={(value: string | undefined) => onAttributionChange(field, value)}
      options={options}
      placeholder={placeholder}
      style={{ minWidth: 150 }}
    />
  )

  return (
    <ErpListPage
      actionPermissions={{ viewDetail: modulePermissionCodes.ordersView }}
      columns={columns}
      data={data}
      description="查询 TikTok Shop 订单、履约和物流状态"
      detailFields={[]}
      enableRowSelection={false}
      filterField="status"
      filterOptions={statusOptions}
      headerFilter={
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Select
            allowClear
            onChange={onShopChange}
            options={shopOptions.map((shop) => ({ value: shop.id, label: shop.shopName }))}
            placeholder="全部店铺"
            style={{ minWidth: 180 }}
            value={selectedShopId}
          />
          {attributionFilter(
            'classificationStatus',
            '判定状态',
            Object.entries(attributionStatusLabels).map(([value, label]) => ({ value, label })),
          )}
        </div>
      }
      onFilterChange={(value) => onStatusChange(value as OrderStatus | undefined)}
      onOpenDetail={onOpenDetail}
      onPageChange={onPageChange}
      onReset={onReset}
      onSearchChange={onSearchChange}
      pagination={pagination}
      searchFields={['orderNumber', 'platformOrderId', 'itemSummary']}
      serverSide
      title="订单列表"
    />
  )
}
