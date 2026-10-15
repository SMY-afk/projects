export const financePaymentStatusLabels: Record<string, string> = {
  paid: '已付款',
  pending: '待付款',
  processing: '付款中',
  failed: '付款失败',
  cancelled: '已取消',
}

export const financePaymentStatusLabel = (status: string) => financePaymentStatusLabels[status.toLowerCase()] ?? status

export const financeStatementStatusLabels: Record<string, string> = {
  available: '可用',
  pending: '待处理',
  processing: '处理中',
  settled: '已结算',
  completed: '已完成',
  closed: '已关闭',
  failed: '失败',
  cancelled: '已取消',
}

export const financeStatementStatusLabel = (status: string) =>
  financeStatementStatusLabels[status.toLowerCase()] ?? status

export const financeTransactionTypeLabels: Record<string, string> = {
  order: '订单',
  adjustment: '调整',
  reserve: '准备金',
  refund: '退款',
}

export const financeTransactionTypeLabel = (type: string) => financeTransactionTypeLabels[type.toLowerCase()] ?? type

export const financeIssueLabels: Record<string, string> = {
  transaction_identity: '流水恒等式差异',
  missing_order: '订单未关联',
  statement_transaction: '结算单与流水差异',
  payment_statement: '付款与结算差异',
  orphan_payment: '付款未关联结算单',
}

export const financeStatusColor = (status: string) => {
  const normalized = status.toLowerCase()
  if (['paid', 'settled', 'available', 'matched', 'complete'].includes(normalized)) return 'green'
  if (['failed', 'mismatched', 'unavailable'].includes(normalized)) return 'red'
  return 'gold'
}
