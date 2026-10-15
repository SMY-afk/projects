import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router'
import type { FinanceReconciliationItem } from '../types/finance.types'
import { formatFinanceMoney, formatFinanceTime } from './finance-format'
import { financeIssueLabels } from './finance-labels'

export function FinanceReconciliationTable({
  items,
  loading,
  timezone,
}: {
  items: FinanceReconciliationItem[]
  loading: boolean
  timezone?: string | null
}) {
  const columns: ColumnsType<FinanceReconciliationItem> = [
    {
      title: '问题类型',
      dataIndex: 'kind',
      fixed: 'left',
      width: 190,
      render: (value: string) => financeIssueLabels[value] ?? value,
    },
    {
      title: '参考编号',
      dataIndex: 'reference',
      width: 220,
      render: (value: string, row) =>
        row.entityType === 'statement' ? <Link to={`/finance/statements/${row.entityId}`}>{value}</Link> : value,
    },
    {
      title: '对象',
      dataIndex: 'entityType',
      width: 110,
      render: (value: string) => ({ statement: '结算单', transaction: '流水', payment: '付款' })[value] ?? value,
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 100,
      render: (value: string) => <Tag color={value === 'high' ? 'red' : 'gold'}>{value === 'high' ? '高' : '中'}</Tag>,
    },
    {
      title: '预期金额',
      align: 'right',
      width: 140,
      render: (_, row) => formatFinanceMoney(row.expectedAmountMinor, row.currency),
    },
    {
      title: '实际金额',
      align: 'right',
      width: 140,
      render: (_, row) => formatFinanceMoney(row.actualAmountMinor, row.currency),
    },
    {
      title: '差异',
      align: 'right',
      width: 140,
      render: (_, row) => (
        <Typography.Text type="danger">{formatFinanceMoney(row.differenceMinor, row.currency)}</Typography.Text>
      ),
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
      dataSource={items}
      loading={loading}
      locale={{ emptyText: '未发现对账异常' }}
      pagination={{ defaultPageSize: 20, showSizeChanger: true, showTotal: (total) => `当前快照 ${total} 条` }}
      rowKey={(row) => `${row.kind}-${row.entityType}-${row.entityId}`}
      scroll={{ x: 1200 }}
    />
  )
}
