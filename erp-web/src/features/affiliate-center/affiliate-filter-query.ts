import dayjs from 'dayjs'
import { currentTikTokAffiliateDate } from './affiliate-available-date'
import type { AffiliateFilters } from './components/affiliate-filter-bar'
import type { AffiliateCenterResource } from './types/affiliate-center.types'

const DATE_KEYS: Record<AffiliateCenterResource, readonly [string, string]> = {
  creators: ['creatorFrom', 'creatorTo'],
  videos: ['videoFrom', 'videoTo'],
}

const ROLLING_KEYS: Record<AffiliateCenterResource, string> = {
  creators: 'creatorRolling',
  videos: 'videoRolling',
}

const LEGACY_TODAY_KEYS: Record<AffiliateCenterResource, string> = {
  creators: 'creatorToday',
  videos: 'videoToday',
}

export type AffiliateRollingPreset = 'today' | 'last7d' | 'last30d' | 'last60d'

const ROLLING_DAYS: Record<AffiliateRollingPreset, number> = {
  today: 1,
  last7d: 7,
  last30d: 30,
  last60d: 60,
}

export function affiliateRollingPreset(
  search: string,
  resource: AffiliateCenterResource,
): AffiliateRollingPreset | undefined {
  const params = new URLSearchParams(search)
  const value = params.get(ROLLING_KEYS[resource])
  if (params.get(LEGACY_TODAY_KEYS[resource]) === '1') return 'today'
  return value === 'today' || value === 'last7d' || value === 'last30d' || value === 'last60d' ? value : undefined
}

export function isAffiliateTodayRolling(search: string, resource: AffiliateCenterResource) {
  return affiliateRollingPreset(search, resource) === 'today'
}

export function isAffiliateFixedWindow(search: string, resource: AffiliateCenterResource) {
  return new URLSearchParams(search).get(ROLLING_KEYS[resource]) === 'fixed'
}

export function affiliateRollingPresetForRange(
  filters: AffiliateFilters,
  latestAvailableDay: string,
): AffiliateRollingPreset | undefined {
  if (filters.to !== latestAvailableDay) return undefined
  const days = dayjs(filters.to).diff(dayjs(filters.from), 'day') + 1
  return (Object.entries(ROLLING_DAYS).find(([, value]) => value === days)?.[0] as AffiliateRollingPreset) ?? undefined
}

export function affiliateLegacyRollingPresetForRange(
  filters: AffiliateFilters,
  latestAvailableDay: string,
): AffiliateRollingPreset | undefined {
  const lagDays = dayjs(latestAvailableDay).diff(dayjs(filters.to), 'day')
  if (lagDays < 1 || lagDays > 2) return undefined
  const days = dayjs(filters.to).diff(dayjs(filters.from), 'day') + 1
  return (Object.entries(ROLLING_DAYS).find(([, value]) => value === days)?.[0] as AffiliateRollingPreset) ?? undefined
}

export function rollAffiliateFiltersToLatest(
  filters: AffiliateFilters,
  latestAvailableDay: string,
  preset: AffiliateRollingPreset,
) {
  return {
    ...filters,
    from: dayjs(latestAvailableDay)
      .subtract(ROLLING_DAYS[preset] - 1, 'day')
      .format('YYYY-MM-DD'),
    to: latestAvailableDay,
  }
}

export function clampAffiliateFiltersToLatest(filters: AffiliateFilters, latestAvailableDay: string) {
  if (filters.to <= latestAvailableDay) return filters
  const durationDays = Math.max(0, dayjs(filters.to).diff(dayjs(filters.from), 'day'))
  return {
    ...filters,
    from: dayjs(latestAvailableDay).subtract(durationDays, 'day').format('YYYY-MM-DD'),
    to: latestAvailableDay,
  }
}

export function readAffiliateFilters(search: string, resource: AffiliateCenterResource): AffiliateFilters {
  const params = new URLSearchParams(search)
  const [fromKey, toKey] = DATE_KEYS[resource]
  const latestAvailableDay = dayjs(currentTikTokAffiliateDate(null))
  return {
    shopId: params.get('shopId') ?? '',
    from: params.get(fromKey) ?? params.get('from') ?? latestAvailableDay.subtract(6, 'day').format('YYYY-MM-DD'),
    to: params.get(toKey) ?? params.get('to') ?? latestAvailableDay.format('YYYY-MM-DD'),
    currency: params.get('currency') ?? 'USD',
  }
}

export function hasCompleteAffiliateFilterQuery(search: string, resource: AffiliateCenterResource) {
  const params = new URLSearchParams(search)
  return Boolean(params.get('shopId')) && Boolean(params.get('currency')) && hasAffiliateDateQuery(search, resource)
}

export function hasAffiliateDateQuery(search: string, resource: AffiliateCenterResource) {
  const params = new URLSearchParams(search)
  const [fromKey, toKey] = DATE_KEYS[resource]
  return (
    (Boolean(params.get(fromKey)) && Boolean(params.get(toKey))) ||
    (Boolean(params.get('from')) && Boolean(params.get('to')))
  )
}

export function writeAffiliateFilterSearch(
  search: string,
  resource: AffiliateCenterResource,
  filters: AffiliateFilters,
  rollingPreset?: AffiliateRollingPreset | false,
) {
  const params = new URLSearchParams(search)
  const [fromKey, toKey] = DATE_KEYS[resource]
  params.set('shopId', filters.shopId)
  params.set('currency', filters.currency)
  params.set(fromKey, filters.from)
  params.set(toKey, filters.to)
  params.delete('from')
  params.delete('to')
  params.delete(LEGACY_TODAY_KEYS[resource])
  if (rollingPreset) params.set(ROLLING_KEYS[resource], rollingPreset)
  if (rollingPreset === false) params.set(ROLLING_KEYS[resource], 'fixed')
  return params.toString()
}

export function switchAffiliateResourceSearch(
  search: string,
  currentResource: AffiliateCenterResource,
  currentFilters: AffiliateFilters,
  targetResource: AffiliateCenterResource,
) {
  const params = new URLSearchParams(search)
  const [currentFromKey, currentToKey] = DATE_KEYS[currentResource]
  if (!params.get(currentFromKey) || !params.get(currentToKey)) {
    params.set(currentFromKey, currentFilters.from)
    params.set(currentToKey, currentFilters.to)
  }
  if (!params.get('shopId')) params.set('shopId', currentFilters.shopId)
  if (!params.get('currency')) params.set('currency', currentFilters.currency)
  params.delete('from')
  params.delete('to')
  const [targetFromKey, targetToKey] = DATE_KEYS[targetResource]
  if (!params.get(targetFromKey) || !params.get(targetToKey)) {
    params.delete(targetFromKey)
    params.delete(targetToKey)
    params.delete(ROLLING_KEYS[targetResource])
  }
  return params.toString()
}
