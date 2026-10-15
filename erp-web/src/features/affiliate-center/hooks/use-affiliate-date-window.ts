import { useEffect } from 'react'
import {
  affiliateLegacyRollingPresetForRange,
  affiliateRollingPreset,
  affiliateRollingPresetForRange,
  clampAffiliateFiltersToLatest,
  hasCompleteAffiliateFilterQuery,
  isAffiliateFixedWindow,
  rollAffiliateFiltersToLatest,
  type AffiliateRollingPreset,
} from '../affiliate-filter-query'
import type { AffiliateFilters } from '../components/affiliate-filter-bar'
import type { AffiliateCenterResource } from '../types/affiliate-center.types'

type WriteFilters = (
  filters: AffiliateFilters,
  replace?: boolean,
  rollingPreset?: AffiliateRollingPreset | false,
) => void

export function useAffiliateDateWindow(
  filters: AffiliateFilters,
  latestAvailableDay: string | undefined,
  search: string,
  resource: AffiliateCenterResource,
  writeFilters: WriteFilters,
) {
  useEffect(() => {
    if (!filters.shopId || !latestAvailableDay || !hasCompleteAffiliateFilterQuery(search, resource)) return
    const storedPreset = affiliateRollingPreset(search, resource)
    const fixedWindow = isAffiliateFixedWindow(search, resource)
    if (fixedWindow) return
    const clamped = clampAffiliateFiltersToLatest(filters, latestAvailableDay)
    if (clamped !== filters) {
      writeFilters(clamped, true, storedPreset ?? false)
      return
    }
    const preset =
      storedPreset ??
      affiliateRollingPresetForRange(filters, latestAvailableDay) ??
      (fixedWindow ? undefined : affiliateLegacyRollingPresetForRange(filters, latestAvailableDay))
    if (!preset) return
    const rolled = rollAffiliateFiltersToLatest(filters, latestAvailableDay, preset)
    if (!storedPreset || rolled.from !== filters.from || rolled.to !== filters.to) {
      writeFilters(rolled, true, preset)
      return
    }
  }, [filters, latestAvailableDay, resource, search, writeFilters])
}
