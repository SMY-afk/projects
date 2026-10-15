import type { LogisticsStatusLive } from '../types/logistics-status.types'

export function localExcelDate(value: string, timezone: string): Date {
  const instant = new Date(Math.floor(Date.parse(value) / 1000) * 1000)
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(instant)
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, Number(part)]))
  return new Date(Date.UTC(fields.year, fields.month - 1, fields.day, fields.hour, fields.minute, fields.second))
}

export function timezoneHourCorrection(start: string, end: string | null, timezone: string): number {
  if (!end) return 0
  const offset = (value: string) => localExcelDate(value, timezone).getTime() - Math.floor(Date.parse(value) / 1000) * 1000
  return (offset(start) - offset(end)) / 3600_000
}

export function firstPackedEvent(live?: LogisticsStatusLive) {
  return live?.events.filter((event) => event.status === 'ready_for_collection' || event.actionCode === '20101'
    || /order packed and ready for pickup|订单已打包/.test(event.description?.toLowerCase() ?? ''))
    .sort((left, right) => Date.parse(left.occurredAt) - Date.parse(right.occurredAt))[0]
}
