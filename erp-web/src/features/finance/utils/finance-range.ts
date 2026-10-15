import dayjs, { type Dayjs } from 'dayjs'
import timezonePlugin from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)
dayjs.extend(timezonePlugin)

export function defaultFinanceRange(timezone: string, now = new Date()): [Dayjs, Dayjs] {
  const today = dayjs(now).tz(timezone).startOf('day')
  return [today.subtract(29, 'day'), today]
}

export function resolveFinanceRange(range: [Dayjs, Dayjs], timezone: string) {
  const displayFrom = range[0].format('YYYY-MM-DD')
  const displayTo = range[1].format('YYYY-MM-DD')
  const exclusiveEnd = dayjs(displayTo).add(1, 'day').format('YYYY-MM-DD')
  return {
    from: dayjs.tz(displayFrom, timezone).utc().toISOString(),
    to: dayjs.tz(exclusiveEnd, timezone).utc().toISOString(),
  }
}

export function isFinanceDateDisabled(current: Dayjs, from: Dayjs | undefined, maxDate: Dayjs) {
  if (current.startOf('day').isAfter(maxDate.startOf('day'))) return true
  return Boolean(from && Math.abs(current.startOf('day').diff(from.startOf('day'), 'day')) > 29)
}
