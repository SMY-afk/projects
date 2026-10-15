import { Alert, Empty, Spin, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HttpError } from '@/services/http-client'
import type {
  BestsellerAuthorizationStatus,
  BestsellerEntry,
  BestsellerEnvelope,
  BestsellerListData,
  BestsellerRoute,
} from '../types/bestseller.types'
import { creatorRankingColumns } from './creator-ranking-columns'
import { liveRankingColumns } from './live-ranking-columns'
import { productRankingColumns } from './product-ranking-columns'
import { videoRankingColumns } from './video-ranking-columns'

const columns: Record<BestsellerRoute, ColumnsType<BestsellerEntry>> = {
  products: productRankingColumns,
  creators: creatorRankingColumns,
  videos: videoRankingColumns,
  lives: liveRankingColumns,
}

function requestError(error: unknown) {
  if (error instanceof HttpError && error.status === 403) return '当前账号没有畅销榜读取权限。'
  if (error instanceof HttpError && error.status === 404) return '当前租户下未找到所选店铺。'
  if (error instanceof HttpError && error.kind === 'timeout') return '榜单请求超时，请稍后重试。'
  return '无法读取本地畅销榜快照，请稍后重试。'
}

export function BestsellerTable({
  authorization,
  entity,
  query,
  syncing,
}: {
  authorization: {
    data?: BestsellerEnvelope<BestsellerAuthorizationStatus>
    isError: boolean
    isLoading: boolean
  }
  entity: BestsellerRoute
  query: {
    data?: BestsellerEnvelope<BestsellerListData>
    error?: unknown
    isError: boolean
    isLoading: boolean
  }
  syncing: boolean
}) {
  if (authorization.isLoading)
    return (
      <div className="bestseller-table-loading">
        <Spin />
        <span>正在检查店铺授权</span>
      </div>
    )
  if (authorization.isError || !authorization.data)
    return <Alert title="无法确认畅销榜读取授权" showIcon type="error" />
  if (!authorization.data.data.canRead)
    return (
      <Alert
        description="请先完成店铺重新授权；授权完成前不会请求或展示新的榜单数据。"
        title="缺少畅销榜读取授权"
        showIcon
        type="warning"
      />
    )
  if (query.isLoading)
    return (
      <div className="bestseller-table-loading">
        <Spin />
        <span>正在加载榜单</span>
      </div>
    )
  if (query.isError || !query.data) return <Alert title={requestError(query.error)} showIcon type="error" />
  const { data, errors, freshness } = query.data
  const snapshotMissing = errors.some((error) => error.code === 'data_unavailable')
  return (
    <div>
      {syncing && (
        <Alert
          className="bestseller-sync-alert"
          description="同步完成后页面会自动刷新；如已有快照，下方继续展示最近一次成功数据。"
          title="榜单同步中"
          showIcon
          type="info"
        />
      )}
      {snapshotMissing ? (
        <Alert
          className="bestseller-stale-alert"
          description="当前筛选组合尚未同步；请点击“同步当前榜单”生成快照。"
          title="尚无本地快照"
          showIcon
          type="info"
        />
      ) : freshness.isStale ? (
        <Alert
          className="bestseller-stale-alert"
          description={errors[0]?.message ?? '最近一次刷新失败，当前展示最后一次成功榜单。'}
          title="数据可能过期"
          showIcon
          type="warning"
        />
      ) : null}
      {data.items.length ? (
        <Table<BestsellerEntry>
          columns={columns[entity]}
          dataSource={data.items}
          pagination={false}
          rowKey="externalId"
          scroll={{ x: 'max-content', y: 560 }}
          size="middle"
        />
      ) : (
        <Empty
          description={
            errors.some((error) => error.code === 'data_unavailable') ? '尚无已同步榜单' : '当前筛选组合暂无榜单'
          }
        />
      )}
    </div>
  )
}
