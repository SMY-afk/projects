import { Alert, Button, Space, Tag, Typography } from 'antd'
import type { BestsellerAuthorizationStatus, BestsellerEnvelope, BestsellerListData } from '../types/bestseller.types'

export function BestsellerScopeStatus({
  onReauthorize,
  query,
  reauthorizing,
}: {
  onReauthorize: () => void
  query: {
    data?: BestsellerEnvelope<BestsellerAuthorizationStatus>
    isError: boolean
    isLoading: boolean
  }
  reauthorizing: boolean
}) {
  if (query.isLoading) return <Alert title="正在检查店铺 Scope…" showIcon type="info" />
  if (query.isError || !query.data) return <Alert title="无法读取店铺授权状态" showIcon type="error" />
  const status = query.data.data
  if (status.status === 'ready') return null
  if (status.status === 'reauthorization_required') {
    return (
      <Alert
        action={
          <Button loading={reauthorizing} onClick={onReauthorize} size="small" type="primary">
            重新授权
          </Button>
        }
        description={`缺少：${status.missingScopes.join(', ') || '未知 Scope'}`}
        title="需要重新授权店铺"
        showIcon
        type="warning"
      />
    )
  }
  return <Alert title="店铺尚未授权" showIcon type="error" />
}

export function BestsellerSyncStatus({
  envelope,
  queuedCount,
  syncing,
}: {
  envelope?: BestsellerEnvelope<BestsellerListData>
  queuedCount: number
  syncing: boolean
}) {
  const queued = queuedCount > 0
  const snapshotMissing = envelope?.errors.some((error) => error.code === 'data_unavailable') === true
  const label = syncing
    ? '正在提交同步任务'
    : queued
      ? '同步任务已入队'
      : snapshotMissing
        ? '尚未同步'
        : envelope?.freshness.isStale
          ? '数据可能过期'
          : envelope
            ? '数据已更新'
            : '尚无快照'
  const color =
    syncing || queued
      ? 'processing'
      : snapshotMissing
        ? 'default'
        : envelope?.freshness.isStale
          ? 'warning'
          : envelope
            ? 'success'
            : 'default'
  return (
    <Space className="bestseller-sync-status" size="small">
      <Typography.Text type="secondary">同步状态</Typography.Text>
      <Tag color={color}>{label}</Tag>
      {queuedCount > 0 && <Typography.Text type="secondary">{queuedCount} 个任务</Typography.Text>}
      {envelope?.freshness.asOf && (
        <Typography.Text type="secondary">
          快照时间 {new Date(envelope.freshness.asOf).toLocaleString('zh-CN')}
        </Typography.Text>
      )}
    </Space>
  )
}
