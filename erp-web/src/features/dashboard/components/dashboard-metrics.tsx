import { ArrowDownOutlined, ArrowUpOutlined, MinusOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import { metricChange, metricTone, type MetricTone } from './dashboard-metric-utils'

export interface DashboardMetric {
  key: string
  label: string
  value: ReactNode
  category: '销售' | '订单' | '履约' | '店铺'
  current?: number
  previous?: number
  positiveWhenUp?: boolean
  points?: number[]
  status?: string
}

function MetricSparkline({ values, tone }: { values?: number[]; tone: MetricTone }) {
  if (!values?.length) {
    return (
      <div className="metric-status-line" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    )
  }
  const width = 260
  const height = 38
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(max - min, 1)
  const path = values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width
      const y = height - 3 - ((value - min) / span) * (height - 8)
      return `${index ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg className={`metric-sparkline ${tone}`} preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`}>
      <path className="metric-sparkline-fill" d={`${path} L${width},${height} L0,${height} Z`} />
      <path className="metric-sparkline-line" d={path} />
    </svg>
  )
}

export function DashboardMetricCard({ metric }: { metric: DashboardMetric }) {
  const change = metricChange(metric.current, metric.previous)
  const tone = metricTone(change, metric.positiveWhenUp)
  const ChangeIcon =
    change === undefined || change === 0 ? MinusOutlined : change > 0 ? ArrowUpOutlined : ArrowDownOutlined
  return (
    <article className="dashboard-metric-card">
      <div className="metric-card-heading">
        <span>{metric.label}</span>
        <small data-category={metric.category}>{metric.category}</small>
      </div>
      <strong>{metric.value}</strong>
      <div className={`metric-comparison ${tone}`}>
        {change === undefined ? (
          <span>{metric.status ?? '实时状态'}</span>
        ) : (
          <>
            <ChangeIcon />
            <span>{Math.abs(change).toFixed(1)}%</span>
            <small>较上一周期</small>
          </>
        )}
      </div>
      <MetricSparkline tone={tone} values={metric.points} />
    </article>
  )
}
