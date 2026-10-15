import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { isVideoCustomDateDisabled } from '../utils/video-range'

describe('video range controls', () => {
  const today = dayjs('2026-08-19')

  it('disables future dates and dates more than 30 natural days from the first selection', () => {
    expect(isVideoCustomDateDisabled(dayjs('2026-08-20'), undefined, today)).toBe(true)
    expect(isVideoCustomDateDisabled(dayjs('2026-08-19'), dayjs('2026-07-20'), today)).toBe(true)
    expect(isVideoCustomDateDisabled(dayjs('2026-08-19'), dayjs('2026-07-21'), today)).toBe(false)
  })
})
