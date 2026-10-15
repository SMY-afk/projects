import { Card, Col, Row, Statistic, Typography } from 'antd'
import dayjs from 'dayjs'
import { formatCount, formatMoney } from '../affiliate-formatters'
import type {
  AffiliateCenterResource,
  AffiliateCreatorSummary,
  AffiliateVideoSummary,
} from '../types/affiliate-center.types'

interface Props {
  currency?: string
  from: string
  loading: boolean
  resource: AffiliateCenterResource
  summary?: AffiliateCreatorSummary | AffiliateVideoSummary
  to: string
}

interface SummaryItem {
  label: string
  value: string
}

export function AffiliateRangeSummary({ currency, from, loading, resource, summary, to }: Props) {
  const days = dayjs(to).diff(dayjs(from), 'day') + 1
  const items = summaryItems(resource, summary, currency)

  return (
    <Card
      className="affiliate-range-summary"
      loading={loading}
      title={`所选 ${days} 天汇总`}
      extra={<Typography.Text type="secondary">{`${from} 至 ${to}`}</Typography.Text>}
    >
      <Row gutter={[24, 20]}>
        {items.map((item) => (
          <Col key={item.label} xs={12} sm={8} lg={4}>
            <Statistic title={item.label} value={item.value} />
          </Col>
        ))}
      </Row>
    </Card>
  )
}

function summaryItems(
  resource: AffiliateCenterResource,
  summary: AffiliateCreatorSummary | AffiliateVideoSummary | undefined,
  currency?: string,
): SummaryItem[] {
  if (resource === 'creators') {
    const value = summary as AffiliateCreatorSummary | undefined
    return [
      { label: '达人总数', value: formatCount(value?.creatorCount) },
      { label: '联盟 GMV', value: formatMoney(value?.affiliateGmvMinor, currency) },
      { label: '预计佣金', value: formatMoney(value?.estimatedCommissionMinor, currency) },
      { label: '成交件数', value: formatCount(value?.itemsSold) },
      { label: '订单量', value: formatCount(value?.affiliateOrderCount) },
      { label: '商品曝光量', value: formatCount(value?.productImpressions) },
    ]
  }
  const value = summary as AffiliateVideoSummary | undefined
  return [
    { label: '视频总数', value: formatCount(value?.videoCount) },
    { label: 'GMV', value: formatMoney(value?.gmvMinor, currency) },
    { label: '订单量', value: formatCount(value?.orderCount) },
    { label: '成交件数', value: formatCount(value?.itemsSold) },
    { label: '观看量', value: formatCount(value?.views) },
    { label: '商品曝光量', value: formatCount(value?.productImpressions) },
  ]
}
