import { AxiosError, type AxiosAdapter, type AxiosResponse } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authSession } from '@/auth/auth-session'
import { AUTH_FORBIDDEN_EVENT, AUTH_UNAUTHORIZED_EVENT } from '@/auth/auth-events'
import { downloadFile, HttpError, request, unwrapApiResponse } from './http-client'

describe('HTTP client', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('unwraps a successful API response', () => {
    expect(unwrapApiResponse({ code: 0, data: { id: 'P-1' } })).toEqual({ id: 'P-1' })
  })

  it('normalizes failed business responses', () => {
    expect(() => unwrapApiResponse({ code: 'INVALID', message: 'Invalid payload', data: null })).toThrow(HttpError)
  })

  it('adds the active token and unwraps a request response', async () => {
    authSession.setAccessToken('test-token')
    let authorization: string | undefined
    const adapter: AxiosAdapter = (config) => {
      authorization = config.headers?.Authorization as string | undefined
      return Promise.resolve({
        data: { code: 200, data: { id: 'P-1' } },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      })
    }

    await expect(request<{ id: string }>({ method: 'get', url: '/products/P-1', adapter })).resolves.toEqual({
      id: 'P-1',
    })
    expect(authorization).toBe('Bearer test-token')
  })

  it('clears the access token and emits an event for a 401 response', async () => {
    authSession.setAccessToken('expired-token')
    const onUnauthorized = vi.fn()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized)
    const adapter: AxiosAdapter = (config) => Promise.reject(createHttpError(config, 401, 'unauthorized'))

    await expect(request({ method: 'get', url: '/products', adapter })).rejects.toMatchObject({
      status: 401,
      code: 'unauthorized',
    })
    expect(authSession.getAccessToken()).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized)
  })

  it('does not emit a session-expired event when login credentials are rejected', async () => {
    const onUnauthorized = vi.fn()
    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized)
    const adapter: AxiosAdapter = (config) => Promise.reject(createHttpError(config, 401, 'unauthorized'))

    await expect(request({ method: 'post', url: '/auth/login', adapter })).rejects.toMatchObject({
      status: 401,
      code: 'unauthorized',
    })
    expect(onUnauthorized).not.toHaveBeenCalled()
    window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized)
  })

  it('keeps the access token and emits a forbidden event for a 403 response', async () => {
    authSession.setAccessToken('active-token')
    const onForbidden = vi.fn()
    window.addEventListener(AUTH_FORBIDDEN_EVENT, onForbidden)
    const adapter: AxiosAdapter = (config) => Promise.reject(createHttpError(config, 403, 'forbidden'))

    await expect(request({ method: 'get', url: '/shops', adapter })).rejects.toMatchObject({
      status: 403,
      code: 'forbidden',
    })
    expect(authSession.getAccessToken()).toBe('active-token')
    expect(onForbidden).toHaveBeenCalledOnce()
    window.removeEventListener(AUTH_FORBIDDEN_EVENT, onForbidden)
  })

  it('uses FastAPI detail as the normalized error message', async () => {
    const detail = 'TikTok Affiliate data is available through 2026-08-29.'
    const adapter: AxiosAdapter = (config) => Promise.reject(createHttpError(config, 422, 'bad_request', { detail }))

    await expect(request({ method: 'post', url: '/affiliate-center/sync', adapter })).rejects.toMatchObject({
      message: detail,
      status: 422,
    })
  })

  it('reads a structured JSON error returned by a file download', async () => {
    const payload = {
      code: 'affiliate_snapshot_incomplete',
      message: '本土店的视频数据不完整：缺失日期 2026-07-09。',
      shop: '本土店',
      resource: 'videos',
      missingDates: ['2026-07-09'],
    }
    const adapter: AxiosAdapter = (config) =>
      Promise.reject(
        createHttpError(config, 409, payload.code, new Blob([JSON.stringify(payload)], { type: 'application/json' })),
      )

    await expect(downloadFile('/affiliate-center/local-export', { adapter })).rejects.toMatchObject({
      message: payload.message,
      status: 409,
      code: payload.code,
      details: payload,
    })
  })
})

const createHttpError = (
  config: Parameters<AxiosAdapter>[0],
  status: number,
  code: string,
  data: unknown = { code, message: code },
) =>
  new AxiosError('Request failed', 'ERR_BAD_REQUEST', config, undefined, {
    config,
    data,
    headers: {},
    status,
    statusText: 'Error',
  } as AxiosResponse)
