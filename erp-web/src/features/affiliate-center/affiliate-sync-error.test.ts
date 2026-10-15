import { describe, expect, it } from 'vitest'
import { HttpError } from '@/services/http-client'
import { getAffiliateSyncErrorMessage, isAffiliateAvailabilityErrorResolved } from './affiliate-sync-error'

describe('affiliate sync error message', () => {
  it('explains the TikTok latest available day for a 422 response', () => {
    const error = new HttpError('TikTok Affiliate data is available through 2026-08-29.', {
      kind: 'http',
      status: 422,
    })

    expect(getAffiliateSyncErrorMessage('videos', error)).toBe(
      'TikTok 视频数据目前可同步至 2026-08-29，请调整结束日期后重试。',
    )
  })

  it('does not blame the browser for an unrelated validation response', () => {
    const error = new HttpError('Request is invalid.', { kind: 'http', status: 422 })

    expect(getAffiliateSyncErrorMessage('videos', error)).toBe('同步所有视频请求失败：Request is invalid.')
  })

  it('uses the selected shop browser provider for a service-unavailable response', () => {
    const error = new HttpError('TikTok latest available date is unavailable.', { kind: 'http', status: 503 })

    expect(getAffiliateSyncErrorMessage('videos', error, '紫鸟浏览器')).toContain('紫鸟浏览器')
  })

  it('resolves an availability error only after TikTok catches up to the selected end day', () => {
    const message = 'TikTok 视频数据目前可同步至 2026-08-28，请调整结束日期后重试。'

    expect(isAffiliateAvailabilityErrorResolved(message, '2026-08-29', '2026-08-28')).toBe(false)
    expect(isAffiliateAvailabilityErrorResolved(message, '2026-08-29', '2026-08-29')).toBe(true)
  })
})
