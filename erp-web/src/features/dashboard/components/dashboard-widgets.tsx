import type { CSSProperties } from 'react'
import type { DashboardDistributionItem, DashboardTrendPoint, DistributionMetric } from '../types/dashboard.types'
import {
  countryLabel,
  distributionTotal,
  distributionValue,
  formatMoney,
  formatNumber,
  platformLabel,
} from './dashboard-format'

const colors = ['#159c8f', '#4acb9e', '#f1a222', '#4fb0cc', '#92a2ba', '#7c6fd0']

export function DashboardSwitch<T extends string>({
  labels,
  value,
  onChange,
}: {
  labels: Array<{ label: string; value: T }>
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="dashboard-switch">
      {labels.map((item) => (
        <button
          className={item.value === value ? 'active' : ''}
          key={item.value}
          onClick={() => onChange(item.value)}
          type="button"
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

export function TrendGraph({ points, currency }: { points: DashboardTrendPoint[]; currency: string }) {
  const width = 900
  const height = 120
  const maxAmount = Math.max(...points.map((point) => point.salesAmountMinor), 1)
  const maxVolume = Math.max(...points.map((point) => point.salesVolume), 1)
  const line = (values: number[], max: number) =>
    values
      .map((value, index) => {
        const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width
        return `${x},${height - (value / max) * (height - 6)}`
      })
      .join(' ')
  const amountLine = line(
    points.map((point) => point.salesAmountMinor),
    maxAmount,
  )
  const volumeLine = line(
    points.map((point) => point.salesVolume),
    maxVolume,
  )
  const tickIndexes = Array.from(
    new Set([
      0,
      ...Array.from({ length: 5 }, (_, index) => Math.round(((index + 1) * (points.length - 1)) / 6)),
      points.length - 1,
    ]),
  ).filter((index) => index >= 0 && index < points.length)
  return (
    <div className="trend-graph">
      <div className="axis-labels">
        <span>{formatMoney(maxAmount, currency)}</span>
        <span>{formatMoney(Math.round(maxAmount / 2), currency)}</span>
        <span>{formatMoney(0, currency)}</span>
      </div>
      <div className="graph">
        {points.length ? (
          <svg aria-label="销售趋势图" preserveAspectRatio="none" viewBox={`0 0 ${width} ${height}`}>
            <polyline points={amountLine} />
            <polyline className="green" points={volumeLine} />
          </svg>
        ) : (
          <div className="dashboard-empty">当前筛选条件暂无趋势数据</div>
        )}
        <div className="date-axis">
          {tickIndexes.map((index) => (
            <span key={`${points[index]?.date}-${index}`}>{points[index]?.date.slice(5)}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

const valueLabel = (value: number, metric: DistributionMetric, currency: string) =>
  metric === 'salesAmountMinor' ? formatMoney(value, currency) : formatNumber(value)

export function SalesDistribution({
  items,
  metric,
  currency,
}: {
  items: DashboardDistributionItem[]
  metric: DistributionMetric
  currency: string
}) {
  const total = distributionTotal(items, metric)
  let offset = 0
  const slices = items.map((item, index) => {
    const start = total ? (offset / total) * 100 : 0
    offset += distributionValue(item, metric)
    const end = total ? (offset / total) * 100 : 0
    return `${colors[index % colors.length]} ${start}% ${end}%`
  })
  const style = { '--donut-fill': total ? `conic-gradient(${slices.join(',')})` : '#dcefeb' } as CSSProperties
  return (
    <div className="sales-body">
      <div className="sales-donut" style={style}>
        <b>{valueLabel(total, metric, currency)}</b>
        <span>{{ salesVolume: '销量', orderCount: '订单量', salesAmountMinor: '销售额' }[metric]}</span>
      </div>
      <div className="sales-legend">
        {items.length ? (
          items.map((item, index) => {
            const value = distributionValue(item, metric)
            return (
              <div className="legend-row" key={item.key}>
                <span>
                  <i style={{ background: colors[index % colors.length] }} />
                  {platformLabel(item.key)}
                </span>
                <b>
                  {valueLabel(value, metric, currency)}{' '}
                  <small>({total ? ((value / total) * 100).toFixed(2) : '0.00'}%)</small>
                </b>
              </div>
            )
          })
        ) : (
          <span className="dashboard-empty">暂无销售分布数据</span>
        )}
      </div>
    </div>
  )
}

export function OrderDistribution({ items }: { items: DashboardDistributionItem[] }) {
  const total = distributionTotal(items, 'orderCount')
  const first = items[0]
  return (
    <div className="world-map">
      <div className="usa">
        {first ? countryLabel(first.key) : '暂无数据'}
        <b>{first ? formatNumber(first.orderCount) : '0'}</b>
      </div>
      <div className="world-shape" />
      <aside>
        <b>总订单量：{formatNumber(total)}</b>
        <div className="country-list">
          {items.slice(0, 5).map((item) => (
            <span key={item.key}>
              {countryLabel(item.key)}
              <strong>
                {formatNumber(item.orderCount)} {total ? ((item.orderCount / total) * 100).toFixed(2) : '0.00'}%
              </strong>
            </span>
          ))}
        </div>
      </aside>
    </div>
  )
}
