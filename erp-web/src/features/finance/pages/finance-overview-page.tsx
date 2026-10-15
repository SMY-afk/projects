import { useMemo, useState } from 'react'
import { Card, Col, Empty, Row, Space, Tag, Typography, message } from 'antd'
import dayjs from 'dayjs'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { isFinanceMock } from '../api/finance.api'
import { FinanceFeeChart } from '../components/finance-fee-chart'
import { FinanceFilters, type FinanceBasisFilter } from '../components/finance-filters'
import { FinanceKpiCards } from '../components/finance-kpi-cards'
import { FinanceRecentStatements } from '../components/finance-recent-statements'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceStatusBanner } from '../components/finance-status-banner'
import { FinanceTrendChart } from '../components/finance-trend-chart'
import {
  useFinanceExportMutation,
  useFinanceOverviewQuery,
  useFinanceShopsQuery,
  useFinanceStatementsQuery,
} from '../queries/finance.queries'
import { defaultFinanceRange, resolveFinanceRange } from '../utils/finance-range'

import './finance-page.css'

function saveDownload(blob: Blob, fileName = 'finance-statements.csv') {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function FinanceOverviewPage() {
  const shopsQuery = useFinanceShopsQuery()
  const shops = shopsQuery.data ?? []
  const [shopId, setShopId] = useState<string>()
  const [currency, setCurrency] = useState('USD')
  const [basis, setBasis] = useState<FinanceBasisFilter>('all')
  const [range, setRange] = useState(() => defaultFinanceRange('UTC'))
  const selectedShopId = shopId ?? shops[0]?.id
  const selectedShop = shops.find((shop) => shop.id === selectedShopId)
  const timezone = selectedShop?.timezone || 'UTC'
  const window = useMemo(() => resolveFinanceRange(range, timezone), [range, timezone])
  const overviewFilters = {
    shopId: selectedShopId,
    ...window,
    currency,
    isEstimated: basis === 'all' ? undefined : basis === 'estimated',
  }
  const overviewQuery = useFinanceOverviewQuery(overviewFilters, Boolean(selectedShopId))
  const statementsQuery = useFinanceStatementsQuery(
    { page: 1, pageSize: 5, shopId: selectedShopId, ...window, currency },
    Boolean(selectedShopId) && basis !== 'estimated',
  )
  const exportMutation = useFinanceExportMutation()
  const item =
    overviewQuery.data?.items.find((candidate) => candidate.currency === currency) ?? overviewQuery.data?.items[0]

  const refresh = () => {
    void overviewQuery.refetch()
    if (basis !== 'estimated') void statementsQuery.refetch()
  }
  const exportStatements = () => {
    exportMutation.mutate(
      { resource: 'statements', filters: { shopId: selectedShopId, ...window, currency } },
      {
        onSuccess: ({ blob, fileName }) => saveDownload(blob, fileName),
        onError: (error) => void message.error(error instanceof Error ? error.message : '导出失败'),
      },
    )
  }

  if (shopsQuery.isLoading) return <PageLoading fullscreen tip="正在加载财务店铺…" />
  if (shopsQuery.isError) {
    return <PageError title="财务店铺加载失败" onRetry={() => void shopsQuery.refetch()} />
  }
  if (!shops.length) return <Empty description="当前账号暂无可用财务店铺" />
  if (overviewQuery.isLoading) return <PageLoading fullscreen tip="正在汇总财务数据…" />
  if (overviewQuery.isError) {
    return (
      <PageError
        title="财务数据加载失败"
        description={overviewQuery.error instanceof Error ? overviewQuery.error.message : undefined}
        onRetry={() => void overviewQuery.refetch()}
      />
    )
  }

  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <div className="finance-page-header">
        <div>
          <Typography.Title level={2}>财务总览</Typography.Title>
          <Typography.Text type="secondary">店铺时间按 {timezone} 展示；金额按币种最小单位换算。</Typography.Text>
        </div>
        {isFinanceMock ? <Tag color="orange">显式 Mock</Tag> : null}
      </div>
      <FinanceSectionNav />
      <FinanceFilters
        shops={shops}
        shopId={selectedShopId}
        range={range}
        currency={currency}
        basis={basis}
        maxDate={dayjs().tz(timezone).startOf('day')}
        refreshing={Boolean(overviewQuery.isFetching || statementsQuery.isFetching)}
        exporting={exportMutation.isPending}
        onShopChange={setShopId}
        onRangeChange={setRange}
        onCurrencyChange={setCurrency}
        onBasisChange={setBasis}
        onRefresh={refresh}
        onExport={exportStatements}
      />
      {!item ? (
        <Card>
          <Empty description="当前筛选范围暂无财务数据" />
        </Card>
      ) : (
        <>
          <FinanceStatusBanner item={item} />
          <FinanceKpiCards item={item} />
          <Row gutter={[16, 16]}>
            <Col xs={24} xl={16}>
              <FinanceTrendChart points={item.trend} currency={item.currency} />
            </Col>
            <Col xs={24} xl={8}>
              <FinanceFeeChart item={item} />
            </Col>
          </Row>
          <FinanceRecentStatements
            statements={basis === 'estimated' ? [] : (statementsQuery.data?.items ?? [])}
            timezone={timezone}
            loading={basis !== 'estimated' && statementsQuery.isLoading}
            error={basis !== 'estimated' && statementsQuery.isError}
          />
        </>
      )}
    </Space>
  )
}
