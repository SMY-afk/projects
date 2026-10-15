import { Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { BestsellerEntry } from '../types/bestseller.types'
import { extensionNumber, extensionString, formatDuration, formatUnixSeconds } from './bestseller-fields'

export const liveRankingColumns: ColumnsType<BestsellerEntry> = [
  { title: '排名', dataIndex: 'rank', width: 76, fixed: 'left', align: 'center' },
  {
    title: '直播',
    dataIndex: 'displayName',
    width: 260,
    fixed: 'left',
    render: (name: string | null) => <Typography.Text strong>{name ?? '标题待验证'}</Typography.Text>,
  },
  {
    title: '主播',
    width: 180,
    render: (_, entry) =>
      extensionString(entry.extensions, 'creator_nick_name') ??
      extensionString(entry.extensions, 'creator_name') ??
      '—',
  },
  {
    title: '开播时间',
    width: 170,
    render: (_, entry) => formatUnixSeconds(extensionNumber(entry.extensions, 'start_time')),
  },
  {
    title: '直播时长',
    width: 120,
    render: (_, entry) => formatDuration(extensionNumber(entry.extensions, 'duration')),
  },
  { title: '直播 ID', dataIndex: 'externalId', width: 220 },
  { title: 'GMV 区间', width: 180, render: (_, entry) => entry.gmv.raw },
]
