import { Card, Col, Row, Statistic, Typography } from 'antd'
import type { FinanceOverviewItem } from '../types/finance.types'
import { formatFinanceMoney } from './finance-format'

const kpis = [
  { key: 'grossRevenueMinor', title: '销售收入', tone: 'primary' },
  { key: 'refundAmountMinor', title: '退款', tone: 'danger' },
  { key: 'platformFeeMinor', title: '平台费用', tone: 'danger' },
  { key: 'affiliateCommissionMinor', title: '达人佣金', tone: 'danger' },
  { key: 'settlementAmountMinor', title: '结算金额', tone: 'success' },
  { key: 'paidAmountMinor', title: '已付款', tone: 'success' },
  { key: 'outstandingAmountMinor', title: '待付款', tone: 'warning' },
  { key: 'paymentStatementDifferenceMinor', title: '付款差异', tone: 'warning' },
] as const

export function FinanceKpiCards({ item }: { item: FinanceOverviewItem }) {
  return (
    <Row gutter={[16, 16]}>
      {kpis.map((kpi) => (
        <Col key={kpi.key} xs={24} sm={12} lg={6}>
          <Card className={`finance-kpi-card finance-kpi-${kpi.tone}`} size="small">
            <Statistic title={kpi.title} value={formatFinanceMoney(item[kpi.key], item.currency)} />
            {kpi.key === 'paymentStatementDifferenceMinor' && (
              <Typography.Text type="secondary">付款金额 − 结算金额</Typography.Text>
            )}
          </Card>
        </Col>
      ))}
    </Row>
  )
}
