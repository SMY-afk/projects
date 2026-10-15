import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router'
import type { FinanceComponent, FinanceTransaction } from '../types/finance.types'
import { formatFinanceMoney, formatFinanceTime } from './finance-format'
import { financeStatusColor, financeTransactionTypeLabel } from './finance-labels'
import type { FinanceTablePagination } from './finance-table-types'

export function FinanceTransactionTable({
  transactions,
  loading,
  timezone,
  pagination,
}: {
  transactions: FinanceTransaction[]
  loading: boolean
  timezone?: string | null
  pagination?: FinanceTablePagination
}) {
  const componentColumns: ColumnsType<FinanceComponent> = [
    { title: '费用代码', dataIndex: 'componentCode' },
    { title: '类别', dataIndex: 'componentCategory' },
    { title: '平台 SKU', dataIndex: 'platformSkuId', render: (value: string | null) => value ?? '--' },
    {
      title: '金额',
      render: (_, component) => formatFinanceMoney(component.amountMinor, component.currency),
    },
    { title: '说明', dataIndex: 'description', render: (value: string | null) => value ?? '--' },
  ]
  const columns: ColumnsType<FinanceTransaction> = [
    {
      title: '流水号',
      dataIndex: 'platformTransactionId',
      fixed: 'left',
      width: 210,
      render: (value: string | null, row) => value ?? row.id,
    },
    {
      title: '订单',
      width: 160,
      render: (_, row) =>
        row.orderId ? (
          <Link to={row.orderPath ?? `/orders/${row.orderId}`}>{row.orderNumber ?? row.platformOrderId}</Link>
        ) : (
          '--'
        ),
    },
    {
      title: '结算单',
      width: 180,
      render: (_, row) =>
        row.statementId ? (
          <Link to={`/finance/statements/${row.statementId}`}>{row.platformStatementId ?? row.statementId}</Link>
        ) : (
          '--'
        ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (value: string) => financeTransactionTypeLabel(value),
    },
    {
      title: '口径',
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
      title: '退款',
      align: 'right',
      width: 130,
      render: (_, row) => formatFinanceMoney(row.refundAmountMinor, row.currency),
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
      title: '恒等式差异',
      align: 'right',
      width: 140,
      render: (_, row) => (
        <Typography.Text type={row.identityStatus === 'matched' ? 'success' : 'danger'}>
          {formatFinanceMoney(row.identityDifferenceMinor, row.currency)}
        </Typography.Text>
      ),
    },
    {
      title: '发生时间',
      dataIndex: 'occurredAt',
      width: 170,
      render: (value: string) => formatFinanceTime(value, timezone),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => <Tag color={financeStatusColor(value)}>{value}</Tag>,
    },
  ]
  return (
    <Table
      columns={columns}
      dataSource={transactions}
      expandable={{
        expandedRowRender: (row) => (
          <Table
            columns={componentColumns}
            dataSource={row.components}
            locale={{ emptyText: '暂无拆分项' }}
            pagination={false}
            rowKey="id"
            size="small"
          />
        ),
        rowExpandable: (row) => row.components.length > 0,
      }}
      loading={loading}
      locale={{ emptyText: '当前筛选范围暂无财务流水' }}
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
      scroll={{ x: 1750 }}
    />
  )
}
