import { Space, Table, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { formatCount, formatMoney, formatRatio } from '../affiliate-formatters'
import type { AffiliateCreatorMetric, AffiliateDisplayMetric } from '../types/affiliate-center.types'
import { AffiliateAvatar } from './affiliate-avatar'

interface Props {
  currency?: string
  items: AffiliateCreatorMetric[]
  loading: boolean
  page: number
  shopName?: string
  total: number
  metricDefinitions?: AffiliateDisplayMetric[]
  onPageChange: (page: number) => void
  onCreatorOpen?: (creatorId: string) => void
}

export function CreatorMetricTable({
  currency,
  items,
  loading,
  page,
  shopName,
  total,
  metricDefinitions = [],
  onPageChange,
  onCreatorOpen,
}: Props) {
  const definitions = new Map(metricDefinitions.map((item) => [item.field, item.definition]))
  const title = (field: string, label: string) => <Tooltip title={definitions.get(field)}>{label}</Tooltip>
  const columns: ColumnsType<AffiliateCreatorMetric> = [
    {
      title: '店铺名',
      key: 'shopName',
      fixed: 'left',
      width: 180,
      render: () => <Typography.Text ellipsis={{ tooltip: shopName }}>{shopName || '—'}</Typography.Text>,
    },
    {
      title: title('username', '达人'),
      key: 'creator',
      fixed: 'left',
      width: 220,
      render: (_, item) => (
        <Space>
          <AffiliateAvatar alt={item.username} url={item.avatarUrl}>
            {item.username.slice(0, 1).toUpperCase()}
          </AffiliateAvatar>
          <Typography.Link strong onClick={() => onCreatorOpen?.(item.id)}>
            {item.username}
          </Typography.Link>
        </Space>
      ),
    },
    {
      title: '达人身份',
      key: 'identity',
      width: 190,
      render: (_, item) =>
        item.creatorOpenId ? (
          <Tooltip title={item.creatorOpenId}>
            <Typography.Text ellipsis>Open ID · {item.creatorOpenId}</Typography.Text>
          </Tooltip>
        ) : (
          <Typography.Text type="secondary">仅用户名标识</Typography.Text>
        ),
    },
    {
      title: title('affiliateGmvMinor', '联盟 GMV'),
      dataIndex: 'affiliateGmvMinor',
      width: 130,
      render: (value: number | null | undefined) => formatMoney(value, currency),
    },
    {
      title: title('estimatedCommissionMinor', '预计佣金'),
      dataIndex: 'estimatedCommissionMinor',
      width: 130,
      render: (value: number | null | undefined) => formatMoney(value, currency),
    },
    {
      title: title('itemsSold', '成交件数'),
      dataIndex: 'itemsSold',
      width: 110,
      render: formatCount,
    },
    {
      title: title('affiliateOrderCount', '订单量'),
      dataIndex: 'affiliateOrderCount',
      width: 100,
      render: formatCount,
    },
    {
      title: title('averageAffiliateCustomers', '客户数'),
      dataIndex: 'averageAffiliateCustomers',
      width: 110,
      render: formatCount,
    },
    {
      title: title('clickThroughRate', '点击率'),
      dataIndex: 'clickThroughRate',
      width: 100,
      render: formatRatio,
    },
  ]

  return (
    <Table
      rowKey="id"
      columns={columns}
      dataSource={items}
      loading={loading}
      scroll={{ x: 1350 }}
      pagination={{
        current: page,
        pageSize: 50,
        total,
        showSizeChanger: false,
        onChange: onPageChange,
      }}
    />
  )
}
