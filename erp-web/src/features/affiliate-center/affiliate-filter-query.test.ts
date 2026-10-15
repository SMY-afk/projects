import { describe, expect, it } from 'vitest'
import {
  clampAffiliateFiltersToLatest,
  affiliateLegacyRollingPresetForRange,
  affiliateRollingPreset,
  isAffiliateFixedWindow,
  isAffiliateTodayRolling,
  readAffiliateFilters,
  rollAffiliateFiltersToLatest,
  switchAffiliateResourceSearch,
  writeAffiliateFilterSearch,
} from './affiliate-filter-query'

const filters = {
  shopId: 'shop-1',
  from: '2026-08-29',
  to: '2026-08-29',
  currency: 'USD',
}

describe('affiliate today rolling query', () => {
  it('stores the Today mode independently for creators and videos', () => {
    const creatorSearch = writeAffiliateFilterSearch('', 'creators', filters, 'today')
    const videoSearch = writeAffiliateFilterSearch(creatorSearch, 'videos', filters, false)

    expect(isAffiliateTodayRolling(videoSearch, 'creators')).toBe(true)
    expect(isAffiliateTodayRolling(videoSearch, 'videos')).toBe(false)
  })

  it('removes Today mode when a fixed range is selected', () => {
    const rolling = writeAffiliateFilterSearch('', 'creators', filters, 'today')
    const fixed = writeAffiliateFilterSearch(rolling, 'creators', { ...filters, from: '2026-07-31' }, false)

    expect(isAffiliateTodayRolling(fixed, 'creators')).toBe(false)
    expect(isAffiliateFixedWindow(fixed, 'creators')).toBe(true)
  })

  it('migrates a recent legacy seven-day window to rolling mode', () => {
    const legacy = { ...filters, from: '2026-09-01', to: '2026-09-07' }

    expect(affiliateLegacyRollingPresetForRange(legacy, '2026-09-09')).toBe('last7d')
    expect(affiliateLegacyRollingPresetForRange(legacy, '2026-09-10')).toBeUndefined()
  })

  it.each([
    ['today', '2026-08-31', '2026-08-31'],
    ['last7d', '2026-08-25', '2026-08-31'],
    ['last30d', '2026-08-02', '2026-08-31'],
    ['last60d', '2026-07-03', '2026-08-31'],
  ] as const)('rolls %s to the latest TikTok day', (preset, from, to) => {
    const search = writeAffiliateFilterSearch('', 'creators', filters, preset)

    expect(affiliateRollingPreset(search, 'creators')).toBe(preset)
    expect(rollAffiliateFiltersToLatest(filters, '2026-08-31', preset)).toEqual({
      ...filters,
      from,
      to,
    })
  })

  it('keeps rolling modes independent between creators and videos', () => {
    const creators = writeAffiliateFilterSearch('', 'creators', filters, 'last7d')
    const both = writeAffiliateFilterSearch(creators, 'videos', filters, 'last30d')

    expect(affiliateRollingPreset(both, 'creators')).toBe('last7d')
    expect(affiliateRollingPreset(both, 'videos')).toBe('last30d')
  })

  it('clamps an unavailable shop window once while preserving its length', () => {
    expect(clampAffiliateFiltersToLatest({ ...filters, from: '2026-08-01', to: '2026-08-30' }, '2026-08-29')).toEqual({
      ...filters,
      from: '2026-07-31',
      to: '2026-08-29',
    })
  })

  it('keeps a fixed 60-day window unchanged when availability advances', () => {
    const fixed60Days = { ...filters, from: '2026-07-01', to: '2026-08-29' }

    expect(clampAffiliateFiltersToLatest(fixed60Days, '2026-08-30')).toEqual(fixed60Days)
  })

  it('does not copy creator dates into videos on the first tab switch', () => {
    const legacyCreatorSearch = 'shopId=shop-1&from=2026-08-24&to=2026-08-30&currency=USD'
    const switched = switchAffiliateResourceSearch(
      legacyCreatorSearch,
      'creators',
      { ...filters, from: '2026-08-24', to: '2026-08-30' },
      'videos',
    )
    const params = new URLSearchParams(switched)

    expect(params.get('creatorFrom')).toBe('2026-08-24')
    expect(params.get('creatorTo')).toBe('2026-08-30')
    expect(params.get('videoFrom')).toBeNull()
    expect(params.get('videoTo')).toBeNull()
    expect(params.get('from')).toBeNull()
    expect(params.get('to')).toBeNull()
  })

  it('keeps creator dates unchanged when the video range changes', () => {
    const creatorFilters = { ...filters, from: '2026-08-24', to: '2026-08-30' }
    const videoFilters = { ...filters, from: '2026-08-23', to: '2026-08-29' }
    const creatorSearch = writeAffiliateFilterSearch('', 'creators', creatorFilters)
    const separatedSearch = writeAffiliateFilterSearch(creatorSearch, 'videos', videoFilters)
    const changedVideoSearch = writeAffiliateFilterSearch(separatedSearch, 'videos', {
      ...videoFilters,
      from: '2026-08-01',
      to: '2026-08-29',
    })

    expect(readAffiliateFilters(changedVideoSearch, 'creators')).toEqual(creatorFilters)
    expect(readAffiliateFilters(changedVideoSearch, 'videos')).toEqual({
      ...videoFilters,
      from: '2026-08-01',
      to: '2026-08-29',
    })
  })

  it('does not overwrite URL dates with stale filters during a fast tab switch', () => {
    const search =
      'shopId=shop-1&currency=USD&creatorFrom=2026-08-24&creatorTo=2026-08-30&videoFrom=2026-08-01&videoTo=2026-08-07'
    const staleCreatorFilters = { ...filters, from: '2026-07-01', to: '2026-07-31' }

    const switched = switchAffiliateResourceSearch(search, 'creators', staleCreatorFilters, 'videos')

    expect(readAffiliateFilters(switched, 'creators')).toEqual({
      ...filters,
      from: '2026-08-24',
      to: '2026-08-30',
    })
    expect(readAffiliateFilters(switched, 'videos')).toEqual({
      ...filters,
      from: '2026-08-01',
      to: '2026-08-07',
    })
  })
})
