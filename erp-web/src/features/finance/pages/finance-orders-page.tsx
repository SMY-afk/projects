import { useState } from 'react'
import { Card, Empty, Input, Space } from 'antd'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { FinanceListToolbar } from '../components/finance-list-toolbar'
import { FinanceOrderTable } from '../components/finance-order-table'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceWorkspaceHeader } from '../components/finance-workspace-header'
import { useFinanceListScope } from '../hooks/use-finance-list-scope'
import { useFinanceTransactionsQuery } from '../queries/finance.queries'
import type { FinanceOrderPaymentState } from '../types/finance.types'

import './finance-page.css'

export default function FinanceOrdersPage() {
  const scope = useFinanceListScope()
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [keyword, setKeyword] = useState<string>()
  const [paymentState, setPaymentState] = useState<FinanceOrderPaymentState>()
  const query = useFinanceTransactionsQuery(
    {
      page,
      pageSize,
      shopId: scope.selectedShopId,
      ...scope.window,
      currency: scope.currency,
      type: 'ORDER',
      paymentState,
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
        title="订单财务加载失败"
        onRetry={() => void query.refetch()}
        description={query.error instanceof Error ? query.error.message : undefined}
      />
    )

  const resetPage = () => setPage(1)
  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <FinanceWorkspaceHeader title="订单财务" description="按订单号查看付款状态、收入、费用和结算金额。" />
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
        actions={
          <Input.Search
            allowClear
            aria-label="订单号搜索"
            placeholder="订单号"
            onSearch={(value) => {
              setKeyword(value || undefined)
              resetPage()
            }}
            style={{ width: 220 }}
          />
        }
      />
      <Card>
        <FinanceOrderTable
          transactions={query.data?.items ?? []}
          loading={query.isLoading}
          timezone={scope.timezone}
          paymentState={paymentState}
          onPaymentStateChange={(value) => {
            setPaymentState(value)
            resetPage()
          }}
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
