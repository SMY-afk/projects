import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { resolveVideoRange } from './video-range'

describe('video range', () => {
  const now = new Date('2026-08-19T18:00:00Z')

  it.each([
    ['today', '2026-08-19T07:00:00.000Z', '2026-08-20T07:00:00.000Z'],
    ['last7d', '2026-08-13T07:00:00.000Z', '2026-08-20T07:00:00.000Z'],
    ['last30d', '2026-07-21T07:00:00.000Z', '2026-08-20T07:00:00.000Z'],
  ] as const)('resolves %s in the shop timezone', (preset, from, to) => {
    expect(resolveVideoRange({ preset, timezone: 'America/Los_Angeles', now })).toMatchObject({ preset, from, to })
  })

  it('keeps exclusive midnight across daylight saving time', () => {
    const range = resolveVideoRange({
      preset: 'custom',
      timezone: 'America/Los_Angeles',
      now,
      customRange: [dayjs('2026-03-07'), dayjs('2026-03-09')],
    })

    expect(range.from).toBe('2026-03-07T08:00:00.000Z')
    expect(range.to).toBe('2026-03-10T07:00:00.000Z')
    expect(range.displayFrom).toBe('2026-03-07')
    expect(range.displayTo).toBe('2026-03-09')
  })

  it('rejects custom ranges longer than 30 natural days', () => {
    expect(() =>
      resolveVideoRange({
        preset: 'custom',
        timezone: 'UTC',
        now,
        customRange: [dayjs('2026-07-01'), dayjs('2026-07-31')],
      }),
    ).toThrow('30')
  })
})
