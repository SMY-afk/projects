import { useId, useState, type Dispatch, type SetStateAction } from 'react'
import type { DashboardQueryParams, DashboardSnapshot, DashboardTrendPoint } from '../types/dashboard.types'
import { formatMoney, formatNumber } from './dashboard-format'
import { metricChange, metricTone } from './dashboard-metric-utils'
import { DashboardSwitch } from './dashboard-widgets'

type TrendMode = 'sales' | 'orders'

interface DashboardTrendInsightsProps {
  snapshot: DashboardSnapshot
  params: DashboardQueryParams
  onChange: Dispatch<SetStateAction<DashboardQueryParams>>
}

function ChangeIndicator({
  current,
  previous,
  positiveWhenUp = true,
}: {
  current: number
  previous: number
  positiveWhenUp?: boolean
}) {
  const change = metricChange(current, previous)
  const tone = metricTone(change, positiveWhenUp)
  if (change === undefined) return <span className="insight-change neutral">暂无可比基线</span>
  return (
    <span className={`insight-change ${tone}`}>
      {change > 0 ? '↑' : change < 0 ? '↓' : '—'} {Math.abs(change).toFixed(1)}% 较上一周期
    </span>
  )
}

function InsightSummary({
  label,
  value,
  description,
  current,
  previous,
  positiveWhenUp,
}: {
  label: string
  value: string
  description: string
  current: number
  previous: number
  positiveWhenUp?: boolean
}) {
  return (
    <div className="insight-summary-card">
      <span>{label}</span>
      <div className="insight-summary-value">
        <strong>{value}</strong>
        <ChangeIndicator current={current} positiveWhenUp={positiveWhenUp} previous={previous} />
      </div>
      <p>{description}</p>
    </div>
  )
}

function chartSeries(points: DashboardTrendPoint[], mode: TrendMode) {
  if (mode === 'sales') {
    return [
      { key: 'sales', label: '销售额', color: '#e66a22', values: points.map((point) => point.salesAmountMinor) },
      { key: 'net', label: '净销售额', color: '#079c83', values: points.map((point) => point.netSalesAmountMinor) },
    ]
  }
  return [
    { key: 'volume', label: '销量', color: '#079c83', values: points.map((point) => point.salesVolume) },
    { key: 'orders', label: '订单量', color: '#d99a16', values: points.map((point) => point.orderCount) },
  ]
}

function pathFor(values: number[], max: number, width: number, height: number) {
  return values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width
      const y = height - (value / max) * (height - 10)
      return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function BusinessTrendChart({
  points,
  mode,
  currency,
  compact = false,
}: {
  points: DashboardTrendPoint[]
  mode: TrendMode
  currency: string
  compact?: boolean
}) {
  const gradientId = useId().replace(/:/g, '')
  const width = 1200
  const height = compact ? 150 : 210
  const series = chartSeries(points, mode)
  const max = Math.max(...series.flatMap((item) => item.values), 1)
  const tickIndexes = Array.from(
    new Set([
      0,
      ...Array.from({ length: 5 }, (_, index) => Math.round(((index + 1) * (points.length - 1)) / 6)),
      points.length - 1,
    ]),
  ).filter((index) => index >= 0 && index < points.length)
  const formatAxis = (value: number) =>
    mode === 'sales' ? formatMoney(value, currency) : formatNumber(Math.round(value))
  if (!points.length) return <div className="business-chart-empty">当前筛选条件暂无趋势数据</div>
  const primaryPath = pathFor(series[0].values, max, width, height)
  return (
    <div className={`business-trend-chart${compact ? ' compact' : ''}`}>
      <div className="business-chart-legend">
        {series.map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
      <div className="business-chart-layout">
        <div className="business-chart-axis">
          <span>{formatAxis(max)}</span>
          <span>{formatAxis(max / 2)}</span>
          <span>{formatAxis(0)}</span>
        </div>
        <div className="business-chart-canvas">
          <svg
            aria-label={mode === 'sales' ? '销售表现趋势图' : '订单销量趋势图'}
            preserveAspectRatio="none"
            viewBox={`0 0 ${width} ${height}`}
          >
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={series[0].color} stopOpacity="0.16" />
                <stop offset="100%" stopColor={series[0].color} stopOpacity="0" />
              </linearGradient>
            </defs>
            {[0, 0.5, 1].map((ratio) => (
              <line
                className="business-chart-gridline"
                key={ratio}
                x1="0"
                x2={width}
                y1={height * ratio}
                y2={height * ratio}
              />
            ))}
            <path d={`${primaryPath} L${width},${height} L0,${height} Z`} fill={`url(#${gradientId})`} />
            {series.map((item) => (
              <path
                className="business-chart-line"
                d={pathFor(item.values, max, width, height)}
                key={item.key}
                style={{ stroke: item.color }}
              />
            ))}
          </svg>
          <div className="business-chart-dates">
            {tickIndexes.map((index) => (
              <span key={`${points[index]?.date}-${index}`}>{points[index]?.date.slice(5)}</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function periodLabel(snapshot: DashboardSnapshot) {
  const start = snapshot.trend.period.start.slice(0, 10)
  const end = snapshot.trend.period.end.slice(0, 10)
  return `${start} — ${end}`
}

export function DashboardTrendInsights({ snapshot, params, onChange }: DashboardTrendInsightsProps) {
  const [performanceMode, setPerformanceMode] = useState<TrendMode>('sales')
  const { current, previous, points } = snapshot.trend
  return (
    <section className="dashboard-middle">
      <article className="dashboard-panel dashboard-wide-panel">
        <div className="dashboard-panel-title dashboard-middle-title">
          <div>
            <small>ORDER & SALES INSIGHTS</small>
            <h2>订单与销售洞察</h2>
          </div>
          <div className="middle-title-actions">
            <span>{periodLabel(snapshot)}</span>
            <DashboardSwitch
              labels={[
                { label: '近7天', value: 'last7d' },
                { label: '近30天', value: 'last30d' },
                { label: '上月', value: 'lastMonth' },
                { label: '今年', value: 'year' },
              ]}
              value={params.trendRange}
              onChange={(trendRange) => onChange((value) => ({ ...value, trendRange }))}
            />
          </div>
        </div>
        <div className="insight-summary-grid">
          <InsightSummary
            current={current.orderCount}
            description="所选周期内生成的有效订单总数。"
            label="订单量"
            previous={previous.orderCount}
            value={formatNumber(current.orderCount)}
          />
          <InsightSummary
            current={current.salesVolume}
            description="所选周期内订单包含的商品件数。"
            label="销量"
            previous={previous.salesVolume}
            value={formatNumber(current.salesVolume)}
          />
          <InsightSummary
            current={current.cancelledOrderCount}
            description="取消订单下降代表履约质量改善。"
            label="取消订单数"
            positiveWhenUp={false}
            previous={previous.cancelledOrderCount}
            value={formatNumber(current.cancelledOrderCount)}
          />
        </div>
        <div className="middle-chart-heading">
          <strong>订单趋势</strong>
          <span>每个数据点按店铺时区汇总，不包含缺失日期的推算值。</span>
        </div>
        <BusinessTrendChart compact currency={params.currency} mode="orders" points={points} />
      </article>

      <article className="dashboard-panel dashboard-wide-panel performance-trend-panel">
        <div className="dashboard-panel-title dashboard-middle-title">
          <div>
            <small>PERFORMANCE TRENDS</small>
            <h2>经营表现趋势</h2>
          </div>
          <DashboardSwitch
            labels={[
              { label: '销售额 + 净销售额', value: 'sales' },
              { label: '销量 + 订单量', value: 'orders' },
            ]}
            value={performanceMode}
            onChange={setPerformanceMode}
          />
        </div>
        <BusinessTrendChart currency={params.currency} mode={performanceMode} points={points} />
      </article>
    </section>
  )
}
