import dayjs, { type Dayjs } from 'dayjs'
import { useEffect, useState } from 'react'
import { currentTikTokAffiliateDate } from '../affiliate-available-date'
import { affiliateCenterApi } from '../api/affiliate-center.api'
import type { AffiliateVideoListQuery, AffiliateVideoPage } from '../types/affiliate-center.types'

const MAX_LOOKBACK_DAYS = 14

type VideoLoader = (params: AffiliateVideoListQuery) => Promise<AffiliateVideoPage>
const loadAffiliateVideos: VideoLoader = (params) => affiliateCenterApi.listVideos(params)

export async function findLatestCompleteVideoDay(
  shopId: string,
  currency: string,
  anchor: Dayjs,
  loadVideos: VideoLoader = loadAffiliateVideos,
): Promise<string | undefined> {
  for (let offset = 0; offset <= MAX_LOOKBACK_DAYS; offset += 1) {
    const windowEnd = anchor.subtract(offset, 'day')
    try {
      const result = await loadVideos({
        shopId,
        from: windowEnd.subtract(6, 'day').format('YYYY-MM-DD'),
        to: windowEnd.format('YYYY-MM-DD'),
        currency,
        page: 1,
        pageSize: 1,
        sort: 'gmvMinor',
        order: 'desc',
      })
      if (result.run?.status === 'succeeded') return windowEnd.format('YYYY-MM-DD')
    } catch {
      return undefined
    }
  }
  return undefined
}

export function useLatestAffiliateVideoDay(
  enabled: boolean,
  shopId: string,
  currency: string,
  timezone: string | null,
) {
  const lookupKey = enabled && shopId ? `${shopId}:${currency}` : ''
  const [result, setResult] = useState<{ key: string; latestDay?: string }>()

  useEffect(() => {
    let active = true
    if (!lookupKey) return undefined
    void findLatestCompleteVideoDay(shopId, currency, dayjs(currentTikTokAffiliateDate(timezone)).startOf('day')).then(
      (value) => {
        if (active) setResult({ key: lookupKey, latestDay: value })
      },
    )
    return () => {
      active = false
    }
  }, [currency, lookupKey, shopId, timezone])

  return result?.key === lookupKey ? result.latestDay : undefined
}
