import { Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { BestsellerEntry } from '../types/bestseller.types'
import { extensionNumber, extensionString, formatCount } from './bestseller-fields'

export const creatorRankingColumns: ColumnsType<BestsellerEntry> = [
  { title: '排名', dataIndex: 'rank', width: 76, fixed: 'left', align: 'center' },
  {
    title: '创作者',
    dataIndex: 'displayName',
    width: 210,
    fixed: 'left',
    render: (name: string | null) => <Typography.Text strong>{name ?? '—'}</Typography.Text>,
  },
  { title: '用户名', width: 160, render: (_, entry) => extensionString(entry.extensions, 'user_name') ?? '—' },
  { title: 'Open ID', dataIndex: 'externalId', width: 230, ellipsis: true },
  {
    title: '粉丝数',
    width: 120,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'followers_count')),
  },
  {
    title: '获赞数',
    width: 120,
    align: 'right',
    render: (_, entry) => formatCount(extensionNumber(entry.extensions, 'likes_count')),
  },
  { title: 'GMV 区间', width: 170, render: (_, entry) => entry.gmv.raw },
]
