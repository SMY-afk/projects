import { Image, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { formatCount, formatMoney, formatRatio } from '../affiliate-formatters'
import type { AffiliateCreatorDetailItem, AffiliateCreatorDetailResource } from '../types/affiliate-center.types'

interface Props {
  currency: string
  items: AffiliateCreatorDetailItem[]
  loading: boolean
  page: number
  resource: AffiliateCreatorDetailResource
  total: number
  onPageChange: (page: number) => void
}

const contentColumn = (resource: AffiliateCreatorDetailResource) => ({
  title: resource === 'video' ? '带货视频' : resource === 'live' ? '直播' : '商品',
  key: 'content',
  fixed: 'left' as const,
  width: 300,
  render: (_: unknown, item: AffiliateCreatorDetailItem) => (
    <Space>
      {item.coverImageUrl ? (
        <Image height={72} preview={false} src={item.coverImageUrl} width={54} />
      ) : (
        <div className="affiliate-video-cover-placeholder">暂无封面</div>
      )}
      <div>
        <Typography.Text className="affiliate-detail-title" ellipsis strong>
          {item.title || '--'}
        </Typography.Text>
        {item.publishedAt && (
          <div>
            <Typography.Text type="secondary">{dayjs(item.publishedAt).format('YYYY/MM/DD HH:mm')}</Typography.Text>
          </div>
        )}
      </div>
    </Space>
  ),
})

const moneyColumn = (title: string, field: string, currency: string) => ({
  title,
  dataIndex: field,
  width: 130,
  render: (value: number | null | undefined) => formatMoney(value, currency),
})

const countColumn = (title: string, field: string) => ({
  title,
  dataIndex: field,
  width: 110,
  render: formatCount,
})

function columnsFor(
  resource: AffiliateCreatorDetailResource,
  currency: string,
): ColumnsType<AffiliateCreatorDetailItem> {
  const content = contentColumn(resource)
  if (resource === 'video') {
    return [
      content,
      countColumn('观看量', 'views'),
      moneyColumn('GMV', 'gmvMinor', currency),
      countColumn('订单', 'orderCount'),
      countColumn('成交件数', 'itemsSold'),
      {
        title: '点击率',
        dataIndex: 'productClickThroughRate',
        width: 100,
        render: formatRatio,
      },
    ]
  }
  if (resource === 'live') {
    return [
      content,
      moneyColumn('GMV', 'gmvMinor', currency),
      moneyColumn('预计佣金', 'estimatedCommissionMinor', currency),
      countColumn('订单', 'orderCount'),
      countColumn('成交件数', 'itemsSold'),
      countColumn('客户数', 'buyerCount'),
    ]
  }
  if (resource === 'product-card') {
    return [
      content,
      moneyColumn('商品卡 GMV', 'productCardGmvMinor', currency),
      moneyColumn('预计佣金', 'productCardEstimatedCommissionMinor', currency),
      countColumn('成交件数', 'productCardItemsSold'),
      countColumn('客户数', 'productCardBuyerCount'),
    ]
  }
  return [
    content,
    countColumn('曝光', 'productImpressions'),
    countColumn('点击', 'productClicks'),
    moneyColumn('GMV', 'gmvMinor', currency),
    countColumn('订单', 'orderCount'),
    countColumn('成交件数', 'itemsSold'),
    {
      title: '点击率',
      dataIndex: 'productClickThroughRate',
      width: 100,
      render: formatRatio,
    },
  ]
}

export function CreatorDetailTable({ currency, items, loading, page, resource, total, onPageChange }: Props) {
  return (
    <Table
      rowKey="id"
      columns={columnsFor(resource, currency)}
      dataSource={items}
      loading={loading}
      scroll={{ x: 980 }}
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
