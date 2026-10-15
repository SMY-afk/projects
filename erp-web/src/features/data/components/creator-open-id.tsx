import { Tooltip, Typography } from 'antd'

const compactOpenId = (value: string) => (value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value)

export function CreatorOpenId({ value }: { value: unknown }) {
  if (typeof value !== 'string' || !value.trim()) return '--'
  const openId = value.trim()

  return (
    <span className="data-creator-open-id">
      <Tooltip title={openId} placement="topLeft">
        <span className="data-creator-open-id-value">{compactOpenId(openId)}</span>
      </Tooltip>
      <Typography.Text
        className="data-creator-open-id-copy"
        copyable={{ text: openId, tooltips: ['复制完整 Open ID', '已复制'] }}
      />
    </span>
  )
}
