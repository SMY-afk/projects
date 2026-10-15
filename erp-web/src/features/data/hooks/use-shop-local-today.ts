import { useEffect, useState } from 'react'
import dayjs, { type Dayjs } from 'dayjs'
import timezonePlugin from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)
dayjs.extend(timezonePlugin)

function shopLocalToday(timezone?: string): Dayjs {
  return timezone ? dayjs().tz(timezone).startOf('day') : dayjs().startOf('day')
}

function millisecondsUntilNextDay(timezone?: string): number {
  const now = timezone ? dayjs().tz(timezone) : dayjs()
  return Math.max(now.add(1, 'day').startOf('day').diff(now), 1)
}

export function useShopLocalToday(timezone?: string): Dayjs {
  const [today, setToday] = useState(() => shopLocalToday(timezone))

  useEffect(() => {
    let timerId: number | undefined
    const refresh = () => {
      setToday((previous) => {
        const next = shopLocalToday(timezone)
        return previous.isSame(next, 'day') ? previous : next
      })
      timerId = window.setTimeout(refresh, millisecondsUntilNextDay(timezone))
    }

    refresh()
    return () => {
      if (timerId !== undefined) window.clearTimeout(timerId)
    }
  }, [timezone])

  return today
}
