import { Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { BestsellerEntry } from '../types/bestseller.types'
import {
  engagementRate,
  extensionArray,
  extensionNumber,
  formatCount,
  formatDuration,
  formatRate,
  formatUnixSeconds,
} from './bestseller-fields'

function products(entry: BestsellerEntry) {
  return extensionArray(entry.extensions, 'product_infos')
    .map((item) => (item && typeof item === 'object' ? (item as { product_name?: unknown }).product_name : undefined))
    .filter((name): name is string => typeof name === 'string')
}

export const videoRankingColumns: ColumnsType<BestsellerEntry> = [
  { title: '排名', dataIndex: 'rank', width: 76, fixed: 'left', align: 'center' },
  {
    title: '创作者',
    dataIndex: 'displayName',
    width: 190,
    fixed: 'left',
    render: (name: string | null) => <Typography.Text strong>{name ?? '创作者待验证'}</Typography.Text>,
  },
  { title: '视频 ID', dataIndex: 'externalId', width: 190 },
  {
    title: '发布时间',
    width: 170,
    render: (_, entry) => formatUnixSeconds(extensionNumber(entry.extensions, 'publish_time')),
  },
  { title: '时长', width: 100, render: (_, entry) => formatDuration(extensionNumber(entry.extensions, 'duration')) },
  {
    title: '播放量',
    width: 110,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'views')),
  },
  {
    title: '点赞',
    width: 100,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'likes')),
  },
  {
    title: '评论',
    width: 100,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'comments')),
  },
  {
    title: '分享',
    width: 100,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'shares')),
  },
  { title: '互动率', width: 100, align: 'right', render: (_, entry) => formatRate(engagementRate(entry)) },
  {
    title: '关联商品',
    width: 240,
    render: (_, entry) => {
      const names = products(entry)
      return names.length ? names.map((name) => <Tag key={name}>{name}</Tag>) : '—'
    },
  },
  { title: 'GMV 区间', width: 170, render: (_, entry) => entry.gmv.raw },
]
