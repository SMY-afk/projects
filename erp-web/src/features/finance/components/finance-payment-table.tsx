import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { FinanceLinkedPayment, FinancePayment } from '../types/finance.types'
import { formatFinanceMoney, formatFinanceTime } from './finance-format'
import { financePaymentStatusLabel, financeStatusColor } from './finance-labels'
import type { FinanceTablePagination } from './finance-table-types'

type PaymentRow = FinancePayment | FinanceLinkedPayment

export function FinancePaymentTable({
  payments,
  loading,
  timezone,
  pagination,
}: {
  payments: PaymentRow[]
  loading: boolean
  timezone?: string | null
  pagination?: FinanceTablePagination
}) {
  const columns: ColumnsType<PaymentRow> = [
    { title: '付款单号', dataIndex: 'platformPaymentId', fixed: 'left', width: 220 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => <Tag color={financeStatusColor(value)}>{financePaymentStatusLabel(value)}</Tag>,
    },
    {
      title: '付款金额',
      align: 'right',
      width: 140,
      render: (_, row) => formatFinanceMoney(row.paymentAmountMinor, row.currency),
    },
    {
      title: '关联结算金额',
      align: 'right',
      width: 150,
      render: (_, row) =>
        'statementAmountMinor' in row ? formatFinanceMoney(row.statementAmountMinor, row.currency) : '--',
    },
    {
      title: '差异',
      align: 'right',
      width: 130,
      render: (_, row) =>
        'differenceMinor' in row ? (
          <Typography.Text type={row.recexample81340158 === 'matched' ? 'success' : 'danger'}>
            {formatFinanceMoney(row.differenceMinor, row.currency)}
          </Typography.Text>
        ) : (
          '--'
        ),
    },
    {
      title: '银行参考',
      dataIndex: 'bankReferenceMasked',
      width: 140,
      render: (value: string | null) => value ?? '--',
    },
    {
      title: '发起时间',
      dataIndex: 'initiatedAt',
      width: 170,
      render: (value: string) => formatFinanceTime(value, timezone),
    },
    {
      title: '到账时间',
      dataIndex: 'paidAt',
      width: 170,
      render: (value: string | null) => formatFinanceTime(value, timezone),
    },
  ]
  return (
    <Table
      columns={columns}
      dataSource={payments}
      loading={loading}
      locale={{ emptyText: '当前筛选范围暂无付款记录' }}
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
      scroll={{ x: 1180 }}
    />
  )
}
