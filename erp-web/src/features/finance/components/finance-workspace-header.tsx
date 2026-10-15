import { Tag, Typography } from 'antd'
import { isFinanceMock } from '../api/finance.api'

export function FinanceWorkspaceHeader({ title, description }: { title: string; description: string }) {
  return (
    <div className="finance-page-header">
      <div>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      {isFinanceMock ? <Tag color="orange">显式 Mock</Tag> : null}
    </div>
  )
}
