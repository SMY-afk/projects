export function formatAffiliateLastUpdatedAt(value?: string, timezone?: string | null): string {
  if (!value) return '暂无数据'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '暂无数据'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'medium',
    ...(timezone ? { timeZone: timezone } : {}),
  }).format(date)
}
