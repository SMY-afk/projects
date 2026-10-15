import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router'
import type { FinanceOrderPaymentState, FinanceTransaction } from '../types/finance.types'
import { formatFinanceMoney, formatFinanceTime } from './finance-format'
import type { FinanceTablePagination } from './finance-table-types'

function orderPaymentState(row: FinanceTransaction): FinanceOrderPaymentState {
  if (row.basis === 'estimated' || row.status.toUpperCase() === 'UNSETTLED') return 'pending'
  if (row.refundAmountMinor !== 0) return 'refunded'
  return 'completed'
}

function renderOrderPaymentState(row: FinanceTransaction) {
  const state = orderPaymentState(row)
  if (state === 'pending') return <Tag color="orange">待付款</Tag>
  if (state === 'refunded') return <Tag color="red">已付款后退款</Tag>
  return <Tag color="green">已经完结</Tag>
}

export function FinanceOrderTable({
  transactions,
  loading,
  timezone,
  pagination,
  paymentState,
  onPaymentStateChange,
}: {
  transactions: FinanceTransaction[]
  loading: boolean
  timezone?: string | null
  pagination?: FinanceTablePagination
  paymentState?: FinanceOrderPaymentState
  onPaymentStateChange?: (paymentState?: FinanceOrderPaymentState) => void
}) {
  const columns: ColumnsType<FinanceTransaction> = [
    {
      title: '订单号',
      fixed: 'left',
      width: 190,
      render: (_, row) => {
        const orderNumber = row.orderNumber ?? row.platformOrderId ?? '--'
        return row.orderId ? <Link to={row.orderPath ?? `/orders/${row.orderId}`}>{orderNumber}</Link> : orderNumber
      },
    },
    {
      key: 'paymentState',
      title: '状态',
      width: 130,
      filters: [
        { text: '已经完结', value: 'completed' },
        { text: '已付款后退款', value: 'refunded' },
        { text: '待付款', value: 'pending' },
      ],
      filterMultiple: false,
      filteredValue: paymentState ? [paymentState] : null,
      render: (_, row) => renderOrderPaymentState(row),
    },
    {
      title: '金额类型',
      dataIndex: 'basis',
      width: 90,
      render: (value: string) => (
        <Tag color={value === 'settled' ? 'green' : 'orange'}>{value === 'settled' ? '最终' : '预计'}</Tag>
      ),
    },
    {
      title: '收入',
      align: 'right',
      width: 130,
      render: (_, row) => formatFinanceMoney(row.revenueAmountMinor, row.currency),
    },
    {
      title: '费用',
      align: 'right',
      width: 130,
      render: (_, row) => formatFinanceMoney(row.feeAmountMinor, row.currency),
    },
    {
      title: '结算金额',
      align: 'right',
      width: 140,
      render: (_, row) => formatFinanceMoney(row.settlementAmountMinor, row.currency),
    },
    {
      title: '发生时间',
      dataIndex: 'occurredAt',
      width: 170,
      render: (value: string) => formatFinanceTime(value, timezone),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={transactions}
      loading={loading}
      locale={{ emptyText: '当前筛选范围暂无订单财务记录' }}
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
      scroll={{ x: 900 }}
      onChange={(_, filters) => {
        const nextState = filters.paymentState?.[0]
        const normalizedState = typeof nextState === 'string' ? (nextState as FinanceOrderPaymentState) : undefined
        if (normalizedState !== paymentState) onPaymentStateChange?.(normalizedState)
      }}
    />
  )
}
