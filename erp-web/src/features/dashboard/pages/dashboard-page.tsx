import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { DashboardContent } from '../components/dashboard-content'
import { dashboardQueryKeys, useDashboardSnapshotQuery } from '../queries/dashboard.queries'
import type { DashboardQueryParams } from '../types/dashboard.types'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { defaultDashboardParams } from './dashboard-defaults'

export default function DashboardPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useState<DashboardQueryParams>(defaultDashboardParams)
  const dashboardQuery = useDashboardSnapshotQuery(params)

  if (dashboardQuery.isLoading) return <PageLoading fullscreen />
  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <PageError
        title="Dashboard 数据加载失败"
        description="真实数据接口请求失败，页面不会回退到 Mock 数据。"
        onRetry={() => void dashboardQuery.refetch()}
      />
    )
  }
  return (
    <DashboardContent
      loading={dashboardQuery.isFetching}
      onChange={setParams}
      onRefresh={() => void queryClient.invalidateQueries({ queryKey: dashboardQueryKeys.all })}
      params={params}
      snapshot={dashboardQuery.data}
    />
  )
}
