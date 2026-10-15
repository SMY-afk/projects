import { Card, Col, Row, Statistic, Typography } from 'antd'
import type { BestsellerEntry, BestsellerRoute } from '../types/bestseller.types'
import {
  engagementRate,
  extensionArray,
  extensionNumber,
  extensionNumeric,
  extensionString,
  formatCount,
  formatDuration,
  formatRate,
} from './bestseller-fields'

interface Metric {
  label: string
  value: string | number
}

const median = (values: number[]): number | undefined => {
  if (!values.length) return undefined
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

const numbers = (entries: BestsellerEntry[], key: string) =>
  entries.map((entry) => extensionNumber(entry.extensions, key)).filter((value): value is number => value !== undefined)

const uniqueStrings = (entries: BestsellerEntry[], key: string) =>
  new Set(entries.map((entry) => extensionString(entry.extensions, key)).filter(Boolean)).size

function productMetrics(entries: BestsellerEntry[]): Metric[] {
  const rated = entries.filter((entry) => extensionNumeric(entry.extensions, 'rating') !== undefined).length
  return [
    { label: '上榜商品', value: entries.length },
    { label: '覆盖店铺', value: uniqueStrings(entries, 'shop_name') },
    { label: '有评分商品', value: rated },
    { label: '榜首 GMV 区间', value: entries[0]?.gmv.raw ?? '—' },
  ]
}

function creatorMetrics(entries: BestsellerEntry[]): Metric[] {
  const followers = numbers(entries, 'followers_count')
  const likes = numbers(entries, 'likes_count')
  return [
    { label: '上榜达人', value: entries.length },
    { label: '粉丝中位数', value: formatCount(median(followers)) },
    { label: '累计获赞', value: formatCount(likes.reduce((total, value) => total + value, 0)) },
    { label: '榜首达人', value: entries[0]?.displayName ?? '—' },
  ]
}

function videoMetrics(entries: BestsellerEntry[]): Metric[] {
  const rates = entries.map(engagementRate).filter((value): value is number => value !== undefined)
  const products = new Set(
    entries.flatMap((entry) =>
      extensionArray(entry.extensions, 'product_infos')
        .map((item) => (item && typeof item === 'object' ? (item as { product_id?: unknown }).product_id : undefined))
        .filter((value): value is string => typeof value === 'string'),
    ),
  )
  return [
    { label: '上榜视频', value: entries.length },
    { label: '总播放量', value: formatCount(numbers(entries, 'views').reduce((total, value) => total + value, 0)) },
    { label: '互动率中位数', value: formatRate(median(rates)) },
    { label: '关联商品', value: products.size },
  ]
}

function liveMetrics(entries: BestsellerEntry[]): Metric[] {
  return [
    { label: '上榜直播', value: entries.length },
    { label: '上榜主播', value: uniqueStrings(entries, 'creator_name') },
    { label: '直播时长中位数', value: formatDuration(median(numbers(entries, 'duration'))) },
    { label: '榜首主播', value: extensionString(entries[0]?.extensions ?? {}, 'creator_nick_name') ?? '—' },
  ]
}

const titles: Record<BestsellerRoute, string> = {
  products: '选品概览',
  creators: '达人筛选概览',
  videos: '视频内容表现',
  lives: '直播内容表现',
}

export function BestsellerInsights({ entity, entries }: { entity: BestsellerRoute; entries: BestsellerEntry[] }) {
  if (!entries.length) return null
  const metrics =
    entity === 'products'
      ? productMetrics(entries)
      : entity === 'creators'
        ? creatorMetrics(entries)
        : entity === 'videos'
          ? videoMetrics(entries)
          : liveMetrics(entries)
  return (
    <section className="bestseller-insights">
      <div className="bestseller-insights-heading">
        <Typography.Title level={5}>{titles[entity]}</Typography.Title>
        <Typography.Text type="secondary">基于当前官方周期榜单，不计算 GMV 合计或跨期增长率</Typography.Text>
      </div>
      <Row gutter={[12, 12]}>
        {metrics.map((metric) => (
          <Col key={metric.label} xs={12} lg={6}>
            <Card className="bestseller-insight-card" size="small">
              <Statistic title={metric.label} value={metric.value} />
            </Card>
          </Col>
        ))}
      </Row>
    </section>
  )
}
