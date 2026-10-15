import { useState } from 'react'
import { Card, Empty, Select, Space } from 'antd'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { FinanceListToolbar } from '../components/finance-list-toolbar'
import { financePaymentStatusLabels } from '../components/finance-labels'
import { FinancePaymentTable } from '../components/finance-payment-table'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceWorkspaceHeader } from '../components/finance-workspace-header'
import { useFinanceListScope } from '../hooks/use-finance-list-scope'
import { useFinancePaymentsQuery } from '../queries/finance.queries'

import './finance-page.css'

export default function FinancePaymentsPage() {
  const scope = useFinanceListScope()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<string>()
  const query = useFinancePaymentsQuery(
    {
      page,
      pageSize,
      shopId: scope.selectedShopId,
      ...scope.window,
      currency: scope.currency,
      status,
    },
    Boolean(scope.selectedShopId),
  )
  if (scope.shopsQuery.isLoading) return <PageLoading fullscreen tip="正在加载财务店铺…" />
  if (scope.shopsQuery.isError)
    return <PageError title="财务店铺加载失败" onRetry={() => void scope.shopsQuery.refetch()} />
  if (!scope.shops.length) return <Empty description="当前账号暂无可用财务店铺" />
  if (query.isError)
    return (
      <PageError
        title="付款记录加载失败"
        onRetry={() => void query.refetch()}
        description={query.error instanceof Error ? query.error.message : undefined}
      />
    )
  const resetPage = () => setPage(1)
  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <FinanceWorkspaceHeader title="付款" description="查看平台付款状态、关联结算金额与到账差异。" />
      <FinanceSectionNav />
      <FinanceListToolbar
        shops={scope.shops}
        shopId={scope.selectedShopId}
        range={scope.range}
        currency={scope.currency}
        maxDate={scope.maxDate}
        onShopChange={(value) => {
          scope.setShopId(value)
          resetPage()
        }}
        onRangeChange={(value) => {
          scope.setRange(value)
          resetPage()
        }}
        onCurrencyChange={(value) => {
          scope.setCurrency(value)
          resetPage()
        }}
        extra={
          <label className="finance-filter-field">
            <span>付款状态</span>
            <Select
              allowClear
              aria-label="付款状态"
              onChange={(value) => {
                setStatus(value)
                resetPage()
              }}
              options={Object.entries(financePaymentStatusLabels).map(([value, label]) => ({
                value: value.toUpperCase(),
                label,
              }))}
              placeholder="全部"
              style={{ width: 120 }}
              value={status}
            />
          </label>
        }
      />
      <Card>
        <FinancePaymentTable
          payments={query.data?.items ?? []}
          loading={query.isLoading}
          timezone={scope.timezone}
          pagination={{
            current: page,
            pageSize,
            total: query.data?.total ?? 0,
            onChange: (nextPage, nextSize) => {
              setPage(nextPage)
              setPageSize(nextSize)
            },
          }}
        />
      </Card>
    </Space>
  )
}
