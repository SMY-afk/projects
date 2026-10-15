import { describe, expect, it } from 'vitest'
import { HttpError } from '@/services/http-client'
import { resyncErrorMessage } from './resync-error-message'

describe('resyncErrorMessage', () => {
  it('does not describe an expired login as a platform outage', () => {
    expect(resyncErrorMessage(new HttpError('unauthorized', { status: 401 }))).toEqual({
      title: '登录已失效',
      description: '请重新登录后再次发起同步。',
    })
  })

  it('distinguishes permission, rate-limit, timeout, and service failures', () => {
    expect(resyncErrorMessage(new HttpError('forbidden', { status: 403 })).title).toBe('无同步权限')
    expect(resyncErrorMessage(new HttpError('rate limited', { status: 429 })).title).toBe('同步请求过于频繁')
    expect(resyncErrorMessage(new HttpError('timeout', { kind: 'timeout' })).title).toBe('同步请求超时')
    expect(resyncErrorMessage(new HttpError('unavailable', { status: 503 })).title).toBe('重新同步未提交')
  })
})
