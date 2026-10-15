import { describe, expect, it } from 'vitest'
import { defaultDashboardParams } from './dashboard-defaults'

describe('dashboard default query', () => {
  it('uses the TikTok shop timezone instead of the browser timezone', () => {
    expect(defaultDashboardParams().timezone).toBe('America/Los_Angeles')
  })
})
