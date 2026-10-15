export interface ObservabilityConfig {
  environment: string
  release: string
  errorEndpoint?: string
  metricsEndpoint?: string
  enabled: boolean
}

export interface Metric {
  name: string
  value: number
  unit?: string
  tags?: Record<string, string | number | boolean>
}

const readEnv = (key: string): string | undefined => {
  const value = (import.meta.env as Record<string, unknown>)[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

export const observabilityConfig: ObservabilityConfig = {
  environment: readEnv('VITE_RELEASE_ENVIRONMENT') ?? import.meta.env.MODE,
  release: readEnv('VITE_RELEASE_VERSION') ?? 'local',
  errorEndpoint: readEnv('VITE_ERROR_REPORTING_ENDPOINT'),
  metricsEndpoint: readEnv('VITE_METRICS_ENDPOINT'),
  enabled: readEnv('VITE_OBSERVABILITY_ENABLED') !== 'false',
}

const context = () => ({
  environment: observabilityConfig.environment,
  release: observabilityConfig.release,
  url: window.location.href,
})

const send = (endpoint: string | undefined, body: unknown) => {
  if (!observabilityConfig.enabled || !endpoint) return
  const payload = JSON.stringify(body)
  if (typeof navigator.sendBeacon === 'function') {
    navigator.sendBeacon(endpoint, new Blob([payload], { type: 'application/json' }))
    return
  }
  void fetch(endpoint, {
    method: 'POST',
    body: payload,
    headers: { 'content-type': 'application/json' },
    keepalive: true,
  }).catch(() => undefined)
}

export const captureError = (error: unknown, extra: Record<string, unknown> = {}) => {
  const normalized =
    error instanceof Error ? { name: error.name, message: error.message, stack: error.stack } : { value: error }
  send(observabilityConfig.errorEndpoint, {
    type: 'error',
    ...context(),
    error: normalized,
    ...extra,
    timestamp: new Date().toISOString(),
  })
}

export const trackMetric = (metric: Metric) => {
  send(observabilityConfig.metricsEndpoint, {
    type: 'metric',
    ...context(),
    ...metric,
    timestamp: new Date().toISOString(),
  })
}

export const initializeObservability = () => {
  if (!observabilityConfig.enabled || typeof window === 'undefined') return
  window.addEventListener('error', (event) =>
    captureError(event.error ?? new Error(event.message), { source: 'window' }),
  )
  window.addEventListener('unhandledrejection', (event) => captureError(event.reason, { source: 'unhandledrejection' }))

  const paintObserver =
    typeof PerformanceObserver !== 'undefined'
      ? new PerformanceObserver((list) => {
          for (const entry of list.getEntries())
            trackMetric({ name: entry.name, value: entry.startTime, unit: 'ms', tags: { source: 'performance' } })
        })
      : undefined
  paintObserver?.observe({ type: 'paint', buffered: true })
  if (typeof performance !== 'undefined') {
    for (const entry of performance.getEntriesByType('navigation'))
      trackMetric({ name: 'navigation', value: entry.duration, unit: 'ms' })
  }
}

export const trackRequest = (method: string, url: string, duration: number, status?: number) =>
  trackMetric({ name: 'http.request', value: duration, unit: 'ms', tags: { method, url, status: status ?? 'error' } })
