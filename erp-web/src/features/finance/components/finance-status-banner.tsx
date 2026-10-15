import { Alert, Space, Tag, Typography } from 'antd'
import type { FinanceOverviewItem } from '../types/finance.types'
import { formatFinanceMoney } from './finance-format'

const reasonLabels: Record<string, string> = {
  estimated_transactions_present: '包含尚未最终结算的估算交易',
  product_cost_unavailable: '商品成本尚未接入，因此贡献利润和毛利率暂不可用',
  finance_transactions_unavailable: '所选时间范围暂无财务交易',
  statement_transactions_unavailable: '结算单交易明细尚未同步完整',
  payments_unavailable: '付款数据尚未同步完整',
}

const basisLabels = {
  settled: '最终结算',
  estimated: '估算',
  mixed: '最终 + 估算',
  unavailable: '暂无数据',
} as const

const completenessLabels = {
  complete: '数据完整',
  partial: '数据部分完整',
  unavailable: '数据不可用',
} as const

export function FinanceStatusBanner({ item }: { item: FinanceOverviewItem }) {
  const hasDifference = item.statementTransactionDifferenceMinor !== 0 || item.paymentStatementDifferenceMinor !== 0
  const type =
    item.completeness === 'complete' && !hasDifference
      ? 'success'
      : item.completeness === 'unavailable'
        ? 'error'
        : 'warning'
  const reasons = item.missingReasons.map((reason) => reasonLabels[reason] ?? reason)
  if (hasDifference) {
    reasons.push(
      `结算单与交易差异 ${formatFinanceMoney(item.statementTransactionDifferenceMinor, item.currency)}`,
      `付款与结算差异 ${formatFinanceMoney(item.paymentStatementDifferenceMinor, item.currency)}`,
    )
  }
  return (
    <Alert
      showIcon
      type={type}
      title={
        <Space wrap>
          <Typography.Text strong>{completenessLabels[item.completeness]}</Typography.Text>
          <Tag color={item.basis === 'settled' ? 'green' : item.basis === 'estimated' ? 'orange' : 'blue'}>
            {basisLabels[item.basis]}
          </Tag>
        </Space>
      }
      description={reasons.length ? reasons.join('；') : '交易、结算单与付款数据已完成核对。'}
    />
  )
}
