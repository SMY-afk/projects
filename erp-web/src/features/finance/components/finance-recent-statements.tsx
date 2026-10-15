import { Card, Empty, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router'
import type { FinanceStatement } from '../types/finance.types'
import { formatFinanceDate, formatFinanceMoney } from './finance-format'
import { financePaymentStatusLabel, financeStatusColor } from './finance-labels'

export function FinanceRecentStatements({
  statements,
  timezone,
  loading,
  error,
}: {
  statements: FinanceStatement[]
  timezone?: string | null
  loading: boolean
  error: boolean
}) {
  const columns: ColumnsType<FinanceStatement> = [
    {
      title: '结算单号',
      dataIndex: 'platformStatementId',
      render: (value: string, row) => <Link to={`/finance/statements/${row.id}`}>{value}</Link>,
    },
    {
      title: '结算周期',
      render: (_, row) =>
        `${formatFinanceDate(row.statementStartAt, timezone)} — ${formatFinanceDate(row.statementEndAt, timezone)}`,
    },
    {
      title: '结算金额',
      align: 'right',
      render: (_, row) => formatFinanceMoney(row.settlementAmountMinor, row.currency),
    },
    {
      title: '付款状态',
      dataIndex: 'paymentStatus',
      render: (value: string) => <Tag color={financeStatusColor(value)}>{financePaymentStatusLabel(value)}</Tag>,
    },
    {
      title: '核对状态',
      dataIndex: 'recexample81340158',
      render: (value: string) => (
        <Tag color={value === 'matched' ? 'green' : 'red'}>{value === 'matched' ? '已匹配' : '有差异'}</Tag>
      ),
    },
  ]
  return (
    <Card title="最近结算单" extra={<Typography.Text type="secondary">最近 5 条</Typography.Text>}>
      {error ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="结算单加载失败，请刷新重试" />
      ) : (
        <Table
          columns={columns}
          dataSource={statements}
          loading={loading}
          locale={{ emptyText: '当前筛选范围暂无结算单' }}
          pagination={false}
          rowKey="id"
          scroll={{ x: 760 }}
          size="small"
        />
      )}
    </Card>
  )
}
