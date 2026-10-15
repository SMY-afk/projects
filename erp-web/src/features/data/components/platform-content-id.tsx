import { Typography } from 'antd'

export function PlatformContentId({ value }: { value: unknown }) {
  if (typeof value !== 'string' || !value.trim()) return '--'
  const contentId = value.trim()

  return (
    <Typography.Text
      className="data-platform-content-id"
      copyable={{ text: contentId, tooltips: ['复制内容 ID', '已复制'] }}
    >
      {contentId}
    </Typography.Text>
  )
}
