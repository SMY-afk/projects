const ISO_DATE_LENGTH = 10
function calendarDate(timezone: string, now: Date): string {
  const affiliateTimezone = timezone === 'America/Los_Angeles' ? 'Etc/GMT+8' : timezone
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: affiliateTimezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function currentTikTokAffiliateDate(timezone: string | null, now = new Date()): string {
  let localDate: string
  try {
    localDate = calendarDate(timezone || 'UTC', now)
  } catch {
    localDate = calendarDate('UTC', now)
  }
  return localDate.slice(0, ISO_DATE_LENGTH)
}

export function resolveAffiliateLatestAvailableDay(reportedDay: string | undefined): string | undefined {
  return reportedDay
}
