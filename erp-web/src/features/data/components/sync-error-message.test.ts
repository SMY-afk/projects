import { describe, expect, it } from 'vitest'
import { syncErrorMessage } from './sync-error-message'

describe('syncErrorMessage', () => {
  it('uses Chinese explanations for safe analytics failure categories', () => {
    expect(syncErrorMessage('missing_field', null)).toBe('平台返回字段不完整，未写入本地数据。')
    expect(syncErrorMessage('rate_limited', null)).toBe('TikTok 正在限流，请稍后重新同步。')
    expect(syncErrorMessage('timeout', null)).toBe('TikTok 响应超时，请稍后重新同步。')
    expect(syncErrorMessage('platform_error', 'ignored upstream detail')).toBe('平台请求未成功，请稍后重新同步。')
  })

  it('retains only the safe server summary for unknown categories', () => {
    expect(syncErrorMessage('unknown', '安全摘要')).toBe('安全摘要')
    expect(syncErrorMessage(null, null)).toBe('—')
  })
})
