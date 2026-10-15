import { useEffect, useMemo, useRef } from 'react'
import { Card, Empty, Typography } from 'antd'
import type { ECharts } from 'echarts/core'
import type { FinanceOverviewItem } from '../types/finance.types'
import { formatFinanceMoney } from './finance-format'
import type { FinanceChartOption } from './finance-chart-engine'

const feeFields = [
  { key: 'platformFeeMinor', label: '平台费用', color: '#1677ff' },
  { key: 'affiliateCommissionMinor', label: '达人佣金', color: '#722ed1' },
  { key: 'shippingAmountMinor', label: '运费', color: '#13c2c2' },
  { key: 'taxAmountMinor', label: '税费', color: '#fa8c16' },
  { key: 'adjustmentAmountMinor', label: '调整项', color: '#8c8c8c' },
] as const

function buildRows(item: FinanceOverviewItem) {
  return feeFields
    .map((field) => ({ ...field, amountMinor: item[field.key] }))
    .filter((field) => field.amountMinor !== 0)
}

function option(item: FinanceOverviewItem): FinanceChartOption {
  const rows = buildRows(item)
  return {
    animationDuration: 350,
    color: rows.map((row) => row.color),
    tooltip: {
      trigger: 'item',
      formatter: (params: unknown) => {
        const value = params as { name?: string; data?: { signedAmount?: number }; percent?: number }
        return `${value.name ?? '--'}<br/>${formatFinanceMoney(value.data?.signedAmount, item.currency)} · ${value.percent ?? 0}%`
      },
    },
    legend: { show: false },
    series: [
      {
        name: '费用构成',
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '48%'],
        avoidLabelOverlap: true,
        label: { show: false },
        data: rows.map((row) => ({
          name: row.label,
          value: Math.abs(row.amountMinor),
          signedAmount: row.amountMinor,
        })),
      },
    ],
  }
}

export function FinanceFeeChart({ item }: { item: FinanceOverviewItem }) {
  const rows = useMemo(() => buildRows(item), [item])
  const chartOption = useMemo(() => option(item), [item])
  const elementRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = elementRef.current
    if (!element || !rows.length) return
    let chart: ECharts | undefined
    let observer: ResizeObserver | undefined
    let cancelled = false
    void import('./finance-chart-engine').then(({ initFinanceChart }) => {
      if (cancelled) return
      chart = initFinanceChart(element)
      chart.setOption(chartOption)
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(() => chart?.resize())
        observer.observe(element)
      }
    })
    return () => {
      cancelled = true
      observer?.disconnect()
      chart?.dispose()
    }
  }, [chartOption, rows.length])
  return (
    <Card title="费用构成">
      {rows.length ? (
        <div className="finance-fee-layout">
          <div ref={elementRef} className="finance-fee-chart" role="img" aria-label="费用构成图" />
          <ul className="finance-fee-list">
            {rows.map((row) => (
              <li key={row.key}>
                <span className="finance-fee-name">
                  <i style={{ background: row.color }} />
                  {row.label}
                </span>
                <Typography.Text strong>{formatFinanceMoney(row.amountMinor, item.currency)}</Typography.Text>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前范围暂无费用数据" />
      )}
    </Card>
  )
}
