import dayjs, { type Dayjs } from 'dayjs'
import timezonePlugin from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import type { VideoQuery, VideoRange, VideoRangePreset } from '../types/data.types'

dayjs.extend(utc)
dayjs.extend(timezonePlugin)

export interface ResolvedVideoQuery extends Omit<VideoQuery, 'shopId'>, VideoRange {
  displayFrom: string
  displayTo: string
}

export function resolveVideoRange({
  preset,
  timezone,
  now = new Date(),
  customRange,
}: {
  preset: VideoRangePreset
  timezone: string
  now?: Date
  customRange?: [Dayjs, Dayjs]
}): ResolvedVideoQuery {
  const today = dayjs(now).tz(timezone).format('YYYY-MM-DD')
  let displayFrom: string
  let displayTo: string
  if (preset === 'custom') {
    if (!customRange) throw new Error('请选择自定义开始和结束日期')
    displayFrom = customRange[0].format('YYYY-MM-DD')
    displayTo = customRange[1].format('YYYY-MM-DD')
  } else {
    const days = { today: 1, last7d: 7, last30d: 30 }[preset]
    displayFrom = dayjs(today)
      .subtract(days - 1, 'day')
      .format('YYYY-MM-DD')
    displayTo = today
  }
  validateCustomRange(displayFrom, displayTo, today)
  const exclusiveEnd = dayjs(displayTo).add(1, 'day').format('YYYY-MM-DD')
  return {
    preset,
    from: dayjs.tz(displayFrom, timezone).utc().toISOString(),
    to: dayjs.tz(exclusiveEnd, timezone).utc().toISOString(),
    currency: 'USD',
    accountType: 'ALL',
    displayFrom,
    displayTo,
  }
}

export function isVideoCustomDateDisabled(current: Dayjs, from: Dayjs | undefined, maxDate: Dayjs) {
  if (current.startOf('day').isAfter(maxDate.startOf('day'))) return true
  return Boolean(from && Math.abs(current.startOf('day').diff(from.startOf('day'), 'day')) > 29)
}

function validateCustomRange(from: string, to: string, today: string) {
  const start = dayjs(from)
  const end = dayjs(to)
  if (end.isAfter(dayjs(today), 'day')) throw new Error('自定义时间不能包含未来日期')
  if (start.isAfter(end, 'day')) throw new Error('开始日期不能晚于结束日期')
  if (end.diff(start, 'day') + 1 > 30) throw new Error('自定义时间不能超过 30 天')
}
