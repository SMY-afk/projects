import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router'
import type { FinanceStatement } from '../types/finance.types'
import { formatFinanceDate, formatFinanceMoney } from './finance-format'
import { financePaymentStatusLabel, financeStatementStatusLabel, financeStatusColor } from './finance-labels'
import type { FinanceTablePagination } from './finance-table-types'

export function FinanceStatementTable({
  statements,
  loading,
  timezone,
  pagination,
}: {
  statements: FinanceStatement[]
  loading: boolean
  timezone?: string | null
  pagination?: FinanceTablePagination
}) {
  const columns: ColumnsType<FinanceStatement> = [
    {
      title: '结算单号',
      dataIndex: 'platformStatementId',
      fixed: 'left',
      width: 220,
      render: (value: string, row) => <Link to={`/finance/statements/${row.id}`}>{value}</Link>,
    },
    {
      title: '结算周期',
      width: 230,
      render: (_, row) =>
        `${formatFinanceDate(row.statementStartAt, timezone)} — ${formatFinanceDate(row.statementEndAt, timezone)}`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => <Tag color={financeStatusColor(value)}>{financeStatementStatusLabel(value)}</Tag>,
    },
    {
      title: '付款状态',
      dataIndex: 'paymentStatus',
      width: 110,
      render: (value: string) => <Tag color={financeStatusColor(value)}>{financePaymentStatusLabel(value)}</Tag>,
    },
    {
      title: '结算金额',
      align: 'right',
      width: 140,
      render: (_, row) => formatFinanceMoney(row.settlementAmountMinor, row.currency),
    },
    { title: '流水数', dataIndex: 'transactionCount', align: 'right', width: 90 },
    { title: '付款数', dataIndex: 'paymentCount', align: 'right', width: 90 },
    {
      title: '结算/流水差异',
      align: 'right',
      width: 150,
      render: (_, row) => formatFinanceMoney(row.statementTransactionDifferenceMinor, row.currency),
    },
    {
      title: '付款/结算差异',
      align: 'right',
      width: 150,
      render: (_, row) => formatFinanceMoney(row.paymentStatementDifferenceMinor, row.currency),
    },
    {
      title: '核对状态',
      dataIndex: 'recexample81340158',
      width: 110,
      render: (value: string) => (
        <Tag color={financeStatusColor(value)}>{value === 'matched' ? '已匹配' : '有差异'}</Tag>
      ),
    },
  ]
  return (
    <Table
      columns={columns}
      dataSource={statements}
      loading={loading}
      locale={{ emptyText: '当前筛选范围暂无结算单' }}
      pagination={
        pagination && {
          current: pagination.current,
          pageSize: pagination.pageSize,
          total: pagination.total,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: pagination.onChange,
        }
      }
      rowKey="id"
      scroll={{ x: 1400 }}
    />
  )
}
