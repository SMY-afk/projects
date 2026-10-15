import { Image, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { formatCount, formatDateTime, formatMoney, formatRatio } from '../affiliate-formatters'
import type { AffiliateVideoMetric } from '../types/affiliate-center.types'
import { AffiliateAvatar } from './affiliate-avatar'

interface Props {
  currency?: string
  items: AffiliateVideoMetric[]
  loading: boolean
  page: number
  total: number
  onPageChange: (page: number) => void
}

interface VideoCoverProps {
  coverImageUrl?: string | null
  productImageUrl?: string | null
}

function VideoCover({ coverImageUrl, productImageUrl }: VideoCoverProps) {
  const candidates = [coverImageUrl, productImageUrl].filter(
    (value, index, values): value is string => Boolean(value) && values.indexOf(value) === index,
  )
  const [failedUrls, setFailedUrls] = useState<Set<string>>(() => new Set())

  const imageUrl = candidates.find((candidate) => !failedUrls.has(candidate))
  if (!imageUrl) {
    return <div className="affiliate-video-cover-placeholder">无封面</div>
  }
  return (
    <Image
      alt={imageUrl === coverImageUrl ? '视频封面' : '关联商品图片'}
      height={72}
      onError={() => setFailedUrls((current) => new Set(current).add(imageUrl))}
      preview={false}
      src={imageUrl}
      width={54}
    />
  )
}

export function VideoMetricTable({ currency, items, loading, page, total, onPageChange }: Props) {
  const columns: ColumnsType<AffiliateVideoMetric> = [
    {
      title: '视频',
      key: 'video',
      fixed: 'left',
      width: 360,
      render: (_, item) => {
        const productFallback = item.promotedProducts?.find((product) => product.coverImageUrl)?.coverImageUrl
        return (
          <div className="affiliate-video-cell">
            <VideoCover coverImageUrl={item.coverImageUrl} productImageUrl={productFallback} />
            <Typography.Text className="affiliate-video-title" ellipsis={{ tooltip: item.title }}>
              {item.title || '未命名视频'}
            </Typography.Text>
          </div>
        )
      },
    },
    {
      title: '达人',
      key: 'creator',
      width: 210,
      render: (_, item) => {
        const username = item.creatorUsername?.trim()
        const primary = username || '未知达人'
        return (
          <div className="affiliate-video-creator-cell">
            <AffiliateAvatar alt={primary} url={item.creatorAvatarUrl}>
              {primary.slice(0, 1)}
            </AffiliateAvatar>
            <div className="affiliate-video-creator-identity">
              <Typography.Text ellipsis={{ tooltip: primary }}>{primary}</Typography.Text>
            </div>
          </div>
        )
      },
    },
    {
      title: '发布时间',
      dataIndex: 'videoPostTime',
      width: 150,
      className: 'affiliate-video-metric-cell',
      render: formatDateTime,
    },
    {
      title: '商品',
      key: 'products',
      width: 320,
      render: (_, item) =>
        item.promotedProducts?.length ? (
          <div className="affiliate-video-products">
            {item.promotedProducts.slice(0, 2).map((product) => (
              <div className="affiliate-video-product" key={product.productId}>
                {product.coverImageUrl && (
                  <Image
                    alt={product.title || '商品图片'}
                    height={40}
                    preview={false}
                    src={product.coverImageUrl}
                    width={40}
                  />
                )}
                <Typography.Text
                  className="affiliate-video-product-title"
                  ellipsis={{ tooltip: product.title ?? product.productId }}
                >
                  {product.title || product.productId}
                </Typography.Text>
              </div>
            ))}
            {item.promotedProducts.length > 2 && (
              <Typography.Text type="secondary">另有 {item.promotedProducts.length - 2} 件</Typography.Text>
            )}
          </div>
        ) : item.promotedProductIds?.length ? (
          <div className="affiliate-video-products">
            {item.promotedProductIds.slice(0, 2).map((productId) => (
              <div className="affiliate-video-product" key={productId}>
                <div aria-label="商品图片占位" className="affiliate-video-product-placeholder">
                  商品
                </div>
              </div>
            ))}
          </div>
        ) : (
          '—'
        ),
    },
    {
      title: '观看量',
      dataIndex: 'views',
      width: 110,
      className: 'affiliate-video-metric-cell',
      render: formatCount,
    },
    {
      title: 'GMV',
      dataIndex: 'gmvMinor',
      width: 130,
      className: 'affiliate-video-metric-cell',
      render: (value: number | null | undefined) => formatMoney(value, currency),
    },
    {
      title: '订单',
      dataIndex: 'orderCount',
      width: 100,
      className: 'affiliate-video-metric-cell',
      render: formatCount,
    },
    {
      title: '点击率',
      dataIndex: 'productClickThroughRate',
      width: 100,
      className: 'affiliate-video-metric-cell',
      render: formatRatio,
    },
  ]

  return (
    <Table
      className="affiliate-video-table"
      columns={columns}
      dataSource={items}
      loading={loading}
      rowKey="id"
      scroll={{ x: 1490 }}
      tableLayout="fixed"
      pagination={{ current: page, pageSize: 50, total, showSizeChanger: false, onChange: onPageChange }}
    />
  )
}
