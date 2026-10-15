import { useMemo, useState } from 'react'
import { Alert, Card, Empty, Select, Space } from 'antd'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { FinanceListToolbar } from '../components/finance-list-toolbar'
import { financeIssueLabels } from '../components/finance-labels'
import { FinanceReconciliationTable } from '../components/finance-reconciliation-table'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceWorkspaceHeader } from '../components/finance-workspace-header'
import { useFinanceListScope } from '../hooks/use-finance-list-scope'
import { useFinanceReconciliationQuery } from '../queries/finance.queries'

import './finance-page.css'

export default function FinanceReconciliationPage() {
  const scope = useFinanceListScope()
  const [kind, setKind] = useState<string>()
  const [severity, setSeverity] = useState<string>()
  const query = useFinanceReconciliationQuery(
    { shopId: scope.selectedShopId, ...scope.window, currency: scope.currency },
    Boolean(scope.selectedShopId),
  )
  const items = useMemo(
    () =>
      (query.data?.items ?? []).filter(
        (item) => (!kind || item.kind === kind) && (!severity || item.severity === severity),
      ),
    [kind, query.data?.items, severity],
  )
  if (scope.shopsQuery.isLoading) return <PageLoading fullscreen tip="正在加载财务店铺…" />
  if (scope.shopsQuery.isError)
    return <PageError title="财务店铺加载失败" onRetry={() => void scope.shopsQuery.refetch()} />
  if (!scope.shops.length) return <Empty description="当前账号暂无可用财务店铺" />
  if (query.isError)
    return (
      <PageError
        title="对账结果加载失败"
        onRetry={() => void query.refetch()}
        description={query.error instanceof Error ? query.error.message : undefined}
      />
    )
  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <FinanceWorkspaceHeader title="对账" description="集中查看金额恒等式、结算单、付款和订单关联异常。" />
      <FinanceSectionNav />
      <FinanceListToolbar
        shops={scope.shops}
        shopId={scope.selectedShopId}
        range={scope.range}
        currency={scope.currency}
        maxDate={scope.maxDate}
        onShopChange={scope.setShopId}
        onRangeChange={scope.setRange}
        onCurrencyChange={scope.setCurrency}
        extra={
          <>
            <label className="finance-filter-field">
              <span>问题类型</span>
              <Select
                allowClear
                aria-label="对账问题类型"
                value={kind}
                onChange={setKind}
                options={Object.entries(financeIssueLabels).map(([value, label]) => ({ value, label }))}
                placeholder="全部"
                style={{ width: 180 }}
              />
            </label>
            <label className="finance-filter-field">
              <span>严重度</span>
              <Select
                allowClear
                aria-label="对账严重度"
                value={severity}
                onChange={setSeverity}
                options={[
                  { value: 'high', label: '高' },
                  { value: 'medium', label: '中' },
                ]}
                placeholder="全部"
                style={{ width: 100 }}
              />
            </label>
          </>
        }
      />
      <Alert
        showIcon
        type={query.data?.total ? 'warning' : 'success'}
        title={query.data?.total ? `共发现 ${query.data.total} 个对账问题` : '未发现对账问题'}
        description={`当前接口展示最近最多 ${query.data?.limit ?? 100} 条异常；类型与严重度在当前快照内筛选。`}
      />
      <Card>
        <FinanceReconciliationTable items={items} loading={query.isLoading} timezone={scope.timezone} />
      </Card>
    </Space>
  )
}
