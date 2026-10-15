import { useState } from 'react'
import { Card, Empty, Input, Select, Space } from 'antd'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { FinanceListToolbar } from '../components/finance-list-toolbar'
import { financeTransactionTypeLabels } from '../components/finance-labels'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceTransactionTable } from '../components/finance-transaction-table'
import { FinanceWorkspaceHeader } from '../components/finance-workspace-header'
import { useFinanceListScope } from '../hooks/use-finance-list-scope'
import { useFinanceTransactionsQuery } from '../queries/finance.queries'

import './finance-page.css'

export default function FinanceTransactionsPage() {
  const scope = useFinanceListScope()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [status, setStatus] = useState<string>()
  const [type, setType] = useState<string>()
  const [basis, setBasis] = useState<'all' | 'settled' | 'estimated'>('all')
  const [keyword, setKeyword] = useState<string>()
  const query = useFinanceTransactionsQuery(
    {
      page,
      pageSize,
      shopId: scope.selectedShopId,
      ...scope.window,
      currency: scope.currency,
      status,
      type,
      isEstimated: basis === 'all' ? undefined : basis === 'estimated',
      keyword,
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
        title="财务流水加载失败"
        onRetry={() => void query.refetch()}
        description={query.error instanceof Error ? query.error.message : undefined}
      />
    )
  const resetPage = () => setPage(1)
  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <FinanceWorkspaceHeader title="财务流水" description="查看已结算与预计流水、金额恒等式及订单关联。" />
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
          <>
            <label className="finance-filter-field">
              <span>类型</span>
              <Select
                allowClear
                aria-label="流水类型"
                value={type}
                placeholder="全部"
                style={{ width: 110 }}
                options={Object.entries(financeTransactionTypeLabels).map(([value, label]) => ({
                  value: value.toUpperCase(),
                  label,
                }))}
                onChange={(value) => {
                  setType(value)
                  resetPage()
                }}
              />
            </label>
            <label className="finance-filter-field">
              <span>状态</span>
              <Select
                allowClear
                aria-label="流水状态"
                value={status}
                placeholder="全部"
                style={{ width: 110 }}
                options={[
                  { value: 'settled', label: '已结算' },
                  { value: 'PROCESSING', label: '处理中' },
                ]}
                onChange={(value) => {
                  setStatus(value)
                  resetPage()
                }}
              />
            </label>
            <label className="finance-filter-field">
              <span>口径</span>
              <Select
                aria-label="流水口径"
                value={basis}
                style={{ width: 110 }}
                options={[
                  { value: 'all', label: '全部' },
                  { value: 'settled', label: '最终' },
                  { value: 'estimated', label: '预计' },
                ]}
                onChange={(value) => {
                  setBasis(value)
                  resetPage()
                }}
              />
            </label>
          </>
        }
        actions={
          <Input.Search
            allowClear
            aria-label="流水关键字"
            placeholder="流水号或订单号"
            onSearch={(value) => {
              setKeyword(value || undefined)
              resetPage()
            }}
            style={{ width: 210 }}
          />
        }
      />
      <Card>
        <FinanceTransactionTable
          transactions={query.data?.items ?? []}
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
