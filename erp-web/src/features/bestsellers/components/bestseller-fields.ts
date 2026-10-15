export function extensionString(extensions: Record<string, unknown>, key: string): string | undefined {
  const value = extensions[key]
  return typeof value === 'string' && value.trim() ? value : undefined
}

export function extensionNumber(extensions: Record<string, unknown>, key: string): number | undefined {
  const value = extensions[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function extensionNumeric(extensions: Record<string, unknown>, key: string): number | undefined {
  const value = extensions[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string' || !value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

export function extensionArray(extensions: Record<string, unknown>, key: string): unknown[] {
  const value = extensions[key]
  return Array.isArray(value) ? value : []
}

export function formatCount(value?: number): string {
  return value === undefined ? '—' : new Intl.NumberFormat('zh-CN').format(value)
}

export function formatUnixSeconds(value?: number): string {
  if (value === undefined) return '—'
  const date = new Date(value * 1000)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDuration(value?: number): string {
  if (value === undefined || value < 0) return '—'
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const seconds = Math.floor(value % 60)
  if (hours) return `${hours}时${minutes}分`
  if (minutes) return `${minutes}分${seconds}秒`
  return `${seconds}秒`
}

export function engagementRate(entry: { extensions: Record<string, unknown> }): number | undefined {
  const views = extensionNumber(entry.extensions, 'views')
  if (!views) return undefined
  const interactions = ['likes', 'comments', 'shares'].reduce(
    (total, key) => total + (extensionNumber(entry.extensions, key) ?? 0),
    0,
  )
  return interactions / views
}

export function formatRate(value?: number): string {
  return value === undefined
    ? '—'
    : new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 1 }).format(value)
}

export function productImageUrl(extensions: Record<string, unknown>): string | undefined {
  const image = extensions.product_image
  if (!image || typeof image !== 'object') return undefined
  const values = image as { thumb_urls?: unknown; urls?: unknown }
  for (const candidate of [values.thumb_urls, values.urls]) {
    if (Array.isArray(candidate)) {
      const url = candidate.find((item): item is string => typeof item === 'string' && item.length > 0)
      if (url) return url
    }
  }
  return undefined
}
