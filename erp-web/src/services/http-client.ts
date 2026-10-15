import axios, { type AxiosRequestConfig } from 'axios'
import { AUTH_FORBIDDEN_EVENT, AUTH_UNAUTHORIZED_EVENT } from '@/auth/auth-events'
import { authSession } from '@/auth/auth-session'
import { trackRequest } from '@/services/observability'

const REQUEST_TIMEOUT = 10_000
const API_CONTRACT_VERSION =
  typeof import.meta.env.VITE_API_CONTRACT_VERSION === 'string' ? import.meta.env.VITE_API_CONTRACT_VERSION : 'v1'
const getApiBaseUrl = (): string => {
  const apiBaseUrl: unknown = import.meta.env.VITE_API_BASE_URL
  return typeof apiBaseUrl === 'string' ? apiBaseUrl : '/api'
}

export type ApiErrorKind = 'api' | 'http' | 'network' | 'timeout' | 'cancelled' | 'unknown'

export class HttpError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  readonly code?: string
  readonly details?: unknown
  readonly cause?: unknown

  constructor(
    message: string,
    options: { kind?: ApiErrorKind; status?: number; code?: string; details?: unknown; cause?: unknown } = {},
  ) {
    super(message)
    this.name = 'HttpError'
    this.kind = options.kind ?? 'unknown'
    this.status = options.status
    this.code = options.code
    this.details = options.details
    this.cause = options.cause
  }
}

export interface ApiResponse<T> {
  code: string | number
  message?: string
  data: T
}

export interface UploadFileOptions {
  fieldName?: string
  fileName?: string
  data?: Record<string, string | Blob>
  signal?: AbortSignal
  onUploadProgress?: AxiosRequestConfig['onUploadProgress']
}

export interface DownloadFile {
  blob: Blob
  fileName?: string
  contentType?: string
}

const getErrorMessage = (data: unknown): string | undefined => {
  if (!data || typeof data !== 'object') return undefined
  const payload = data as { message?: unknown; msg?: unknown; error?: unknown; detail?: unknown }
  for (const value of [payload.message, payload.msg, payload.error, payload.detail]) {
    if (typeof value === 'string' && value.trim()) return value
  }
  return undefined
}

const normalizeError = (error: unknown): HttpError => {
  if (!axios.isAxiosError<unknown>(error)) {
    return error instanceof HttpError
      ? error
      : new HttpError(error instanceof Error ? error.message : '请求失败', { cause: error })
  }

  const responseData = error.response?.data
  const payload =
    responseData && typeof responseData === 'object' ? (responseData as { code?: unknown; data?: unknown }) : undefined
  const kind: ApiErrorKind = axios.isCancel(error)
    ? 'cancelled'
    : error.code === 'ECONNABORTED'
      ? 'timeout'
      : error.response
        ? 'http'
        : 'network'
  return new HttpError(
    getErrorMessage(responseData) ?? (error.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : '网络请求失败'),
    {
      kind,
      status: error.response?.status,
      code: typeof payload?.code === 'string' ? payload.code : error.code,
      details: responseData,
      cause: error,
    },
  )
}

const normalizeDownloadError = async (error: unknown): Promise<HttpError> => {
  const cause = error instanceof HttpError ? error.cause : error
  if (!axios.isAxiosError<Blob>(cause) || !(cause.response?.data instanceof Blob)) {
    return normalizeError(error)
  }
  const body = await cause.response.data
    .text()
    .then((value) => JSON.parse(value) as unknown)
    .catch(() => null)
  const payload = body && typeof body === 'object' ? (body as { code?: unknown }) : undefined
  return new HttpError(getErrorMessage(body) ?? '文件下载失败', {
    kind: 'http',
    status: cause.response.status,
    code: typeof payload?.code === 'string' ? payload.code : cause.code,
    details: body,
    cause,
  })
}

const isApiResponse = (data: unknown): data is ApiResponse<unknown> =>
  data !== null && typeof data === 'object' && 'code' in data && 'data' in data

const isSuccessfulApiCode = (code: string | number) =>
  code === 0 || code === 200 || code === '0' || code === '200' || code === 'SUCCESS'

const isLoginRequest = (url?: string) => url?.split('?', 1)[0]?.endsWith('/auth/login') ?? false

export const unwrapApiResponse = <T>(data: T | ApiResponse<T>): T => {
  if (!isApiResponse(data)) return data
  if (!isSuccessfulApiCode(data.code)) {
    throw new HttpError(data.message || '请求未成功完成', {
      kind: 'api',
      code: String(data.code),
      details: data,
    })
  }
  return data.data
}

export const httpClient = axios.create({
  baseURL: getApiBaseUrl(),
  timeout: REQUEST_TIMEOUT,
  headers: { 'X-API-Contract-Version': API_CONTRACT_VERSION },
})

httpClient.interceptors.request.use(
  (config) => {
    const accessToken = authSession.getAccessToken()
    if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`
    return config
  },
  (error) => Promise.reject(normalizeError(error)),
)

httpClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401 && !isLoginRequest(error.config?.url)) {
      authSession.clear()
      window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT))
    }
    if (axios.isAxiosError(error) && error.response?.status === 403) {
      window.dispatchEvent(new Event(AUTH_FORBIDDEN_EVENT))
    }
    return Promise.reject(normalizeError(error))
  },
)

export const createRequestController = () => new AbortController()

export const isRequestCancelled = (error: unknown) => error instanceof HttpError && error.kind === 'cancelled'

export const request = async <T>(config: AxiosRequestConfig): Promise<T> => {
  const startedAt = performance.now()
  try {
    const response = await httpClient.request<T | ApiResponse<T>>(config)
    trackRequest(config.method ?? 'get', String(config.url ?? ''), performance.now() - startedAt, response.status)
    return unwrapApiResponse<T>(response.data)
  } catch (error) {
    trackRequest(config.method ?? 'get', String(config.url ?? ''), performance.now() - startedAt)
    throw normalizeError(error)
  }
}

export const uploadFile = async <T>(url: string, file: File, options: UploadFileOptions = {}): Promise<T> => {
  const formData = new FormData()
  formData.append(options.fieldName ?? 'file', file, options.fileName ?? file.name)
  for (const [key, value] of Object.entries(options.data ?? {})) formData.append(key, value)
  return request<T>({
    url,
    method: 'post',
    data: formData,
    signal: options.signal,
    onUploadProgress: options.onUploadProgress,
  })
}

const getDownloadFileName = (contentDisposition?: string): string | undefined => {
  const encodedName = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encodedName) return decodeURIComponent(encodedName)
  return contentDisposition?.match(/filename="?([^";]+)"?/i)?.[1]
}

export const downloadFile = async (
  url: string,
  config: Omit<AxiosRequestConfig, 'url' | 'responseType'> = {},
): Promise<DownloadFile> => {
  try {
    const response = await httpClient.request<Blob>({ ...config, url, responseType: 'blob' })
    const contentDisposition: unknown = response.headers['content-disposition']
    const contentType: unknown = response.headers['content-type']
    return {
      blob: response.data,
      fileName: getDownloadFileName(typeof contentDisposition === 'string' ? contentDisposition : undefined),
      contentType: typeof contentType === 'string' ? contentType : undefined,
    }
  } catch (error) {
    throw await normalizeDownloadError(error)
  }
}
