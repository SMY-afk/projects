import { Typography } from 'antd'

export function VideoRangeSummary({
  displayFrom,
  displayTo,
  asOf,
  timezone,
}: {
  displayFrom: string
  displayTo: string
  asOf?: string | null
  timezone?: string | null
}) {
  const updatedAt = asOf
    ? new Intl.DateTimeFormat('zh-CN', {
        timeZone: timezone ?? undefined,
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
      }).format(new Date(asOf))
    : '同步中'
  return (
    <Typography.Text className="data-video-range-summary" type="secondary">
      统计区间：{displayFrom} ～ {displayTo} · 更新至 {updatedAt}
    </Typography.Text>
  )
}
