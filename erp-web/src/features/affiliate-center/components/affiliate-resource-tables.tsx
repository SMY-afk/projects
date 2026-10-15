import { Card } from 'antd'
import type {
  AffiliateDisplayMetric,
  AffiliateStableCreatorPage,
  AffiliateVideoPage,
} from '../types/affiliate-center.types'
import { CreatorMetricTable } from './creator-metric-table'
import { VideoMetricTable } from './video-metric-table'

interface Props {
  creatorPage?: AffiliateStableCreatorPage
  currency: string
  loading: boolean
  metricDefinitions?: AffiliateDisplayMetric[]
  onCreatorOpen: (creatorId: string) => void
  onPageChange: (page: number) => void
  page: number
  resource: 'creators' | 'videos'
  shopName?: string
  videoPage?: AffiliateVideoPage
}

export function AffiliateResourceTables(props: Props) {
  const { creatorPage, currency, loading, page, resource, shopName, videoPage } = props
  return (
    <Card>
      {resource === 'creators' ? (
        <CreatorMetricTable
          currency={currency}
          items={creatorPage?.items ?? []}
          loading={loading}
          metricDefinitions={props.metricDefinitions}
          page={page}
          shopName={shopName}
          total={creatorPage?.total ?? 0}
          onPageChange={props.onPageChange}
          onCreatorOpen={props.onCreatorOpen}
        />
      ) : (
        <VideoMetricTable
          currency={currency}
          items={videoPage?.items ?? []}
          loading={loading}
          page={page}
          total={videoPage?.total ?? 0}
          onPageChange={props.onPageChange}
        />
      )}
    </Card>
  )
}
