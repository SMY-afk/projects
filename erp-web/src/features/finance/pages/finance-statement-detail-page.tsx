import { ArrowLeftOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Space, Statistic, Tag, Typography } from 'antd'
import { Link, useParams } from 'react-router'
import PageError from '@/shared/components/page-state/page-error'
import PageLoading from '@/shared/components/page-state/page-loading'
import { formatFinanceDate, formatFinanceMoney, formatFinanceTime } from '../components/finance-format'
import {
  financePaymentStatusLabel,
  financeStatementStatusLabel,
  financeStatusColor,
} from '../components/finance-labels'
import { FinancePaymentTable } from '../components/finance-payment-table'
import { FinanceSectionNav } from '../components/finance-section-nav'
import { FinanceTransactionTable } from '../components/finance-transaction-table'
import { FinanceWorkspaceHeader } from '../components/finance-workspace-header'
import { useFinanceShopsQuery, useFinanceStatementQuery } from '../queries/finance.queries'

import './finance-page.css'

export default function FinanceStatementDetailPage() {
  const { statementId = '' } = useParams()
  const query = useFinanceStatementQuery(statementId)
  const shopsQuery = useFinanceShopsQuery()
  if (query.isLoading) return <PageLoading fullscreen tip="正在加载结算单详情…" />
  if (query.isError || !query.data) {
    return (
      <PageError
        title="结算单详情加载失败"
        description={query.error instanceof Error ? query.error.message : undefined}
        onRetry={() => void query.refetch()}
      />
    )
  }
  const statement = query.data
  const timezone = shopsQuery.data?.find((shop) => shop.id === statement.shopId)?.timezone || 'UTC'
  const mismatched = statement.recexample81340158 === 'mismatched'
  return (
    <Space className="finance-page" orientation="vertical" size="large">
      <FinanceWorkspaceHeader
        title="结算单详情"
        description={`结算单 ${statement.platformStatementId} 的金额、流水与付款核对。`}
      />
      <FinanceSectionNav />
      <Link to="/finance/statements">
        <Button icon={<ArrowLeftOutlined />}>返回结算单列表</Button>
      </Link>
      <Alert
        showIcon
        type={mismatched ? 'warning' : 'success'}
        title={mismatched ? '该结算单存在核对差异' : '结算单、流水和付款已匹配'}
        description={
          mismatched
            ? `恒等式差异 ${formatFinanceMoney(statement.identityDifferenceMinor, statement.currency)}；结算/流水差异 ${formatFinanceMoney(statement.statementTransactionDifferenceMinor, statement.currency)}；付款/结算差异 ${formatFinanceMoney(statement.paymentStatementDifferenceMinor, statement.currency)}。`
            : '金额恒等式、流水合计与付款合计均无差异。'
        }
      />
      <Card>
        <Descriptions
          bordered
          column={{ xs: 1, sm: 2, lg: 3 }}
          items={[
            {
              label: '平台结算单号',
              children: <Typography.Text copyable>{statement.platformStatementId}</Typography.Text>,
            },
            {
              label: '结算周期',
              children: `${formatFinanceDate(statement.statementStartAt, timezone)} — ${formatFinanceDate(statement.statementEndAt, timezone)}`,
            },
            {
              label: '结算状态',
              children: (
                <Tag color={financeStatusColor(statement.status)}>{financeStatementStatusLabel(statement.status)}</Tag>
              ),
            },
            {
              label: '付款状态',
              children: (
                <Tag color={financeStatusColor(statement.paymentStatus)}>
                  {financePaymentStatusLabel(statement.paymentStatus)}
                </Tag>
              ),
            },
            { label: '平台创建时间', children: formatFinanceTime(statement.platformCreatedAt, timezone) },
            { label: '同步时间', children: formatFinanceTime(statement.syncedAt, timezone) },
          ]}
        />
      </Card>
      <div className="finance-statement-kpis">
        <Card>
          <Statistic title="销售收入" value={formatFinanceMoney(statement.revenueAmountMinor, statement.currency)} />
        </Card>
        <Card>
          <Statistic title="费用" value={formatFinanceMoney(statement.feeAmountMinor, statement.currency)} />
        </Card>
        <Card>
          <Statistic title="调整项" value={formatFinanceMoney(statement.adjustmentAmountMinor, statement.currency)} />
        </Card>
        <Card>
          <Statistic title="结算金额" value={formatFinanceMoney(statement.settlementAmountMinor, statement.currency)} />
        </Card>
      </div>
      <Card title={`结算流水（${statement.transactions.length}）`}>
        <FinanceTransactionTable transactions={statement.transactions} loading={false} timezone={timezone} />
      </Card>
      <Card title={`关联付款（${statement.payments.length}）`}>
        <FinancePaymentTable payments={statement.payments} loading={false} timezone={timezone} />
      </Card>
    </Space>
  )
}
