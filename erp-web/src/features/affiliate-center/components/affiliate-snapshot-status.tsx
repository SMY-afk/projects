import { CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { Card, Space, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { formatDateTime } from '../affiliate-formatters'
import type {
  AffiliateCenterResource,
  AffiliateCreatorReport,
  AffiliateResourceSyncStatus,
  AffiliateSyncRun,
} from '../types/affiliate-center.types'

const STALE_AFTER_HOURS = 24
const sourceLabels: Record<string, string> = {
  excel: 'Excel 导入',
  excel_upload: 'Excel 导入',
  page_capture: '浏览器监听',
  browser_export: '浏览器导出同步',
  official_api: '官方 API',
}
const statusLabels: Record<string, string> = {
  never_synced: '尚未同步',
  pending: '等待同步',
  running: '同步中',
  succeeded: '同步完成',
  partial: '部分完成',
  failed: '同步失败',
}

interface Props {
  resource: AffiliateCenterResource
  report?: AffiliateCreatorReport | null
  run?: AffiliateSyncRun | null
  status?: AffiliateResourceSyncStatus
}

export function AffiliateSnapshotStatus({ resource, report, run, status }: Props) {
  const snapshot = resource === 'creators' ? report : run
  const latestRun = status?.latestRun
  const latestStatus = status?.status ?? 'never_synced'
  const sourceKind = report?.sourceKind ?? run?.sourceKind ?? latestRun?.sourceKind
  const source = sourceKind
    ? (sourceLabels[sourceKind] ?? sourceKind)
    : run || latestRun
      ? '浏览器监听同步'
      : '暂无数据'
  const collectedAt =
    report?.capturedAt ??
    report?.importedAt ??
    run?.freshAt ??
    run?.finishedAt ??
    latestRun?.freshAt ??
    latestRun?.finishedAt
  const stale = Boolean(collectedAt && dayjs().diff(dayjs(collectedAt), 'hour', true) >= STALE_AFTER_HOURS)
  const partial = latestStatus === 'partial'
  const state = partial ? 'partial' : snapshot ? (stale ? 'stale' : 'complete') : 'missing'
  const countRun = partial ? latestRun : run
  const counts = countRun
    ? `${countRun.persistedCount.toLocaleString()} / ${countRun.fetchedCount.toLocaleString()} 条`
    : report
      ? `${report.rowCount.toLocaleString()} 条`
      : '—'
  const stateView = {
    complete: { color: 'success', icon: <CheckCircleOutlined />, label: `完整 · ${counts}` },
    partial: { color: 'error', icon: <ExclamationCircleOutlined />, label: `部分 · ${counts}` },
    stale: { color: 'warning', icon: <WarningOutlined />, label: `陈旧 · ${counts}` },
    missing: { color: 'default', icon: <ExclamationCircleOutlined />, label: '暂无完整数据' },
  }[state]

  return (
    <Card size="small">
      <Space className="affiliate-status-bar" size="large" wrap>
        <span>
          <Typography.Text type="secondary">数据来源</Typography.Text>
          <Tag color={snapshot ? 'blue' : 'default'}>{source}</Tag>
        </span>
        <span>
          <Typography.Text type="secondary">最近采集时间</Typography.Text>
          <Typography.Text>{formatDateTime(collectedAt)}</Typography.Text>
        </span>
        <span>
          <Typography.Text type="secondary">数据完整性</Typography.Text>
          <Tag
            color={stateView.color}
            icon={stateView.icon}
            title={state === 'stale' ? '最近采集时间已超过 24 小时' : undefined}
          >
            {stateView.label}
          </Tag>
        </span>
        <span>
          <Typography.Text type="secondary">最新同步</Typography.Text>
          <Tag icon={<ClockCircleOutlined />} color={latestStatus === 'failed' || partial ? 'error' : 'default'}>
            {statusLabels[latestStatus] ?? latestStatus}
          </Tag>
        </span>
      </Space>
    </Card>
  )
}
