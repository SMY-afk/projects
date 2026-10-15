const ISO_DATE_LENGTH = 10

function shopCalendarDate(timezone: string, now: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function latestCompletedShopDate(timezone: string | null, now = new Date()): string {
  let localDate: string
  try {
    localDate = shopCalendarDate(timezone || 'UTC', now)
  } catch {
    localDate = shopCalendarDate('UTC', now)
  }
  const startOfLocalDay = new Date(`${localDate}T00:00:00Z`)
  startOfLocalDay.setUTCDate(startOfLocalDay.getUTCDate() - 1)
  return startOfLocalDay.toISOString().slice(0, ISO_DATE_LENGTH)
}
