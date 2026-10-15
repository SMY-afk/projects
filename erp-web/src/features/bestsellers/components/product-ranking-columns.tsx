import { Image, Space, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { BestsellerEntry } from '../types/bestseller.types'
import { extensionNumeric, extensionString, productImageUrl } from './bestseller-fields'

export const productRankingColumns: ColumnsType<BestsellerEntry> = [
  { title: '排名', dataIndex: 'rank', width: 76, fixed: 'left', align: 'center' },
  {
    title: '商品',
    dataIndex: 'displayName',
    width: 290,
    fixed: 'left',
    render: (name: string | null, entry) => {
      const url = productImageUrl(entry.extensions)
      return (
        <Space size="small">
          {url && <Image alt={name ?? '商品图片'} height={40} preview={false} src={url} width={40} />}
          <Typography.Text strong>{name ?? '名称待验证'}</Typography.Text>
        </Space>
      )
    },
  },
  { title: '店铺', width: 190, render: (_, entry) => extensionString(entry.extensions, 'shop_name') ?? '—' },
  {
    title: '评分',
    width: 90,
    align: 'right',
    render: (_, entry) => extensionNumeric(entry.extensions, 'rating') ?? '—',
  },
  { title: '商品 ID', dataIndex: 'externalId', width: 190 },
  {
    title: 'GMV 区间',
    width: 170,
    render: (_, entry) => (
      <span>
        <Typography.Text strong>{entry.gmv.raw}</Typography.Text> <Tag>脱敏区间</Tag>
      </span>
    ),
  },
]
