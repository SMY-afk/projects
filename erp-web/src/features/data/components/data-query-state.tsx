import type { ReactNode } from 'react'
import { Alert, Empty, Spin } from 'antd'
import { HttpError } from '@/services/http-client'
import type { DataEnvelope } from '../types/data.types'

function StaleNotice() {
  return (
    <Alert
      className="data-stale-notice"
      description="尚无可展示的本地快照。可等待计划同步，或由管理员重新同步。"
      title="本地数据暂不可用"
      showIcon
      type="warning"
    />
  )
}

function errorState(error: unknown) {
  if (!(error instanceof HttpError))
    return { title: '平台数据暂不可用', description: '平台或数据服务暂时不可用，请稍后刷新。', type: 'error' as const }
  if (error.status === 401)
    return { title: '登录已失效', description: '请重新登录后再访问店铺数据。', type: 'warning' as const }
  if (error.status === 403)
    return { title: '无访问权限', description: '当前账号没有读取此数据区域的权限。', type: 'warning' as const }
  if (error.status === 429)
    return { title: 'TikTok 正在限流', description: '请求过于频繁，请稍后刷新。', type: 'warning' as const }
  if (error.kind === 'timeout' || error.status === 504)
    return { title: '数据请求超时', description: 'TikTok 响应超时，请稍后刷新。', type: 'error' as const }
  return { title: '平台数据暂不可用', description: '平台或数据服务暂时不可用，请稍后刷新。', type: 'error' as const }
}

export function DataQueryState<T extends unknown[]>({
  query,
  emptyText,
  children,
}: {
  query: { data?: DataEnvelope<T>; error?: unknown; isError: boolean; isLoading: boolean }
  emptyText: string
  children: (data: T) => ReactNode
}) {
  if (query.isLoading) return <Spin />
  if (query.isError || !query.data) {
    const state = errorState(query.error)
    return <Alert description={state.description} title={state.title} showIcon type={state.type} />
  }
  if (query.data.freshness.isStale) return <StaleNotice />
  if (!query.data.data.length) return <Empty description={emptyText} />
  return <>{children(query.data.data)}</>
}
